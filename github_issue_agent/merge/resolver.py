"""Automatic merge-conflict detection and resolution.

Pipeline for every conflicted file:

1. **git rerere** — replay a resolution this repository has already recorded.
2. **Deterministic strategies** — identical sides, whitespace-only differences,
   one-sided changes against the merge base, additive import/dependency unions,
   add/delete conflicts. No model call, no ambiguity.
3. **LLM pass** — only the genuinely semantic hunks are sent to the model, with
   the surrounding file for context, and its answer is rejected unless it
   removes every marker and keeps the file parseable.
4. **Verification** — no markers anywhere, files still parse, then the
   repository's own tests.

Anything still unresolved is reported rather than guessed at, and the caller can
abort the merge cleanly.
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .. import git_ops
from ..llm import LLMProvider
from ..validation.commands import CommandNotAllowed
from ..validation.commands import run as run_command
from .conflicts import (
    ConflictedFile,
    ConflictParseError,
    has_conflict_markers,
    parse_conflicts,
)
from .strategies import Resolution, resolve_blocks

EventHandler = Callable[[str, str], None]

_LLM_SYSTEM = """You resolve git merge conflicts.

You are given a file's full content (with conflict markers) and each conflict
region split into 'ours', 'base' and 'theirs'.

Produce the correct COMBINED result for every conflict:
- keep both sides when they address different concerns;
- when they truly contradict, choose the one that preserves the newer intent and
  keeps the file correct;
- never emit conflict markers;
- never drop unrelated code;
- keep the file syntactically valid and stylistically consistent.

Respond with ONLY this JSON object (no prose, no code fences):
{
  "resolutions": [
    {"index": 0, "lines": ["resolved line 1", "resolved line 2"], "reason": "why"}
  ],
  "unresolved": [{"index": 1, "reason": "why you cannot safely resolve it"}]
}
'lines' must contain the final text of that region, with no markers."""


@dataclass
class FileOutcome:
    path: str
    resolved: bool
    strategies: list[str] = field(default_factory=list)
    remaining: int = 0
    note: str = ""

    def __str__(self) -> str:
        status = "resolved" if self.resolved else f"UNRESOLVED ({self.remaining} hunk(s))"
        detail = ", ".join(dict.fromkeys(self.strategies)) or "-"
        note = f" [{self.note}]" if self.note else ""
        return f"{self.path}: {status} via {detail}{note}"


@dataclass
class ResolutionResult:
    """Outcome of one conflict-resolution run."""

    conflicted: list[str] = field(default_factory=list)
    outcomes: list[FileOutcome] = field(default_factory=list)
    used_llm: bool = False
    validation_output: str = ""
    validation_passed: bool | None = None
    committed: bool = False

    @property
    def resolved_files(self) -> list[str]:
        return [o.path for o in self.outcomes if o.resolved]

    @property
    def unresolved_files(self) -> list[str]:
        return [o.path for o in self.outcomes if not o.resolved]

    @property
    def fully_resolved(self) -> bool:
        return bool(self.conflicted) and not self.unresolved_files

    def report(self) -> str:
        if not self.conflicted:
            return "No merge conflicts detected."
        lines = [f"{len(self.conflicted)} conflicted file(s):"]
        lines += [f"  {outcome}" for outcome in self.outcomes]
        if self.validation_passed is not None:
            lines.append(f"Validation: {'passed' if self.validation_passed else 'FAILED'}")
        return "\n".join(lines)


def detect_conflicts(repo_path: Path) -> list[str]:
    """Files git currently reports as unmerged, plus any stray marker files."""
    conflicted = list(git_ops.conflicted_files(repo_path))
    seen = set(conflicted)
    for path in git_ops.git_raw(repo_path, "ls-files").stdout.splitlines():
        if path in seen or not path.strip():
            continue
        full = repo_path / path
        try:
            if full.is_file() and has_conflict_markers(
                full.read_text(encoding="utf-8", errors="strict")
            ):
                conflicted.append(path)
        except (OSError, UnicodeDecodeError):
            continue
    return conflicted


def _syntax_ok(path: str, content: str) -> tuple[bool, str]:
    if path.endswith(".py"):
        try:
            ast.parse(content)
        except SyntaxError as exc:
            return False, f"python syntax error at line {exc.lineno}: {exc.msg}"
    if path.endswith(".json"):
        try:
            json.loads(content)
        except json.JSONDecodeError as exc:
            return False, f"invalid JSON: {exc}"
    return True, ""


def _handle_add_delete(repo_path: Path, path: str, prefer: str | None) -> FileOutcome | None:
    """Resolve 'modified by one side, deleted by the other' conflicts."""
    stages = git_ops.unmerged_stages(repo_path).get(path, set())
    if 2 in stages and 3 in stages:
        return None  # ordinary content conflict
    if not stages:
        return None
    if prefer == "theirs" and 3 not in stages or prefer == "ours" and 2 not in stages:
        git_ops.git_raw(repo_path, "rm", "-f", "--", path)
        return FileOutcome(path, True, ["delete-per-preference"])
    keep_stage = 2 if 2 in stages else 3
    git_ops.git_raw(repo_path, "checkout", f"--{'ours' if keep_stage == 2 else 'theirs'}", "--", path)
    git_ops.stage(repo_path, [path])
    return FileOutcome(
        path,
        True,
        ["keep-modified-side"],
        note="one side deleted the file; kept the side that still modifies it",
    )


def _llm_resolve(
    provider: LLMProvider,
    path: str,
    parsed: ConflictedFile,
    pending: list[tuple[int, Resolution]],
    guidance: str,
) -> tuple[dict[int, list[str]], list[tuple[int, str]]]:
    blocks = parsed.blocks
    conflict_blocks = "\n\n".join(
        blocks[index].as_prompt(path, index) for index, _ in pending
    )
    hints = "\n".join(
        f"  index {index}: automatic strategies said '{res.strategy}'"
        + (f" - {res.note}" if res.note else "")
        for index, res in pending
    )
    user = (
        f"# File with conflicts: {path}\n\n"
        f"```\n{parsed.render()}\n```\n\n"
        f"# Conflicts to resolve\n{conflict_blocks}\n\n"
        f"# Notes\n{hints}\n"
        + (f"\n# Resolution preference\n{guidance}\n" if guidance else "")
    )
    raw = provider.complete(_LLM_SYSTEM, user)
    data = _extract_json(raw)
    resolutions: dict[int, list[str]] = {}
    failures: list[tuple[int, str]] = []
    if not data:
        return {}, [(index, "model returned no usable JSON") for index, _ in pending]

    valid_indexes = {index for index, _ in pending}
    for item in data.get("resolutions", []) or []:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index", -1))
        except (TypeError, ValueError):
            continue
        if index not in valid_indexes:
            continue
        lines = item.get("lines")
        if isinstance(lines, str):
            lines = lines.split("\n")
        if not isinstance(lines, list):
            failures.append((index, "resolution had no 'lines'"))
            continue
        text_lines = [str(line) for line in lines]
        if any(has_conflict_markers(line) for line in text_lines):
            failures.append((index, "model left conflict markers in the resolution"))
            continue
        resolutions[index] = text_lines

    for index, _ in pending:
        if index not in resolutions and all(index != i for i, _ in failures):
            failures.append((index, "model did not resolve this hunk"))
    return resolutions, failures


def _extract_json(text: str) -> dict | None:
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1)
    start = cleaned.find("{")
    if start == -1:
        return None
    depth = 0
    for index in range(start, len(cleaned)):
        if cleaned[index] == "{":
            depth += 1
        elif cleaned[index] == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(cleaned[start : index + 1])
                except json.JSONDecodeError:
                    return None
                return parsed if isinstance(parsed, dict) else None
    return None


def resolve_file(
    repo_path: Path,
    path: str,
    *,
    provider: LLMProvider | None = None,
    prefer: str | None = None,
    guidance: str = "",
) -> FileOutcome:
    """Resolve every conflict in one file, escalating only what needs a model."""
    add_delete = _handle_add_delete(repo_path, path, prefer)
    if add_delete is not None:
        return add_delete

    full = repo_path / path
    try:
        content = full.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return FileOutcome(path, False, ["binary-or-unreadable"], 1, "not a UTF-8 text file")

    try:
        parsed = parse_conflicts(content, path)
    except ConflictParseError as exc:
        return FileOutcome(path, False, ["unparseable"], 1, str(exc))

    blocks = parsed.blocks
    if not blocks:
        git_ops.stage(repo_path, [path])
        return FileOutcome(path, True, ["already-clean"])

    resolutions, pending = resolve_blocks(blocks, path=path, prefer=prefer)
    strategies = ["deterministic"] if resolutions else []

    if pending and provider is not None:
        llm_resolutions, failures = _llm_resolve(provider, path, parsed, pending, guidance)
        if llm_resolutions:
            strategies.append("llm")
        resolutions.update(llm_resolutions)
        pending = [(index, res) for index, res in pending if index not in llm_resolutions]
        note = "; ".join(f"hunk {index}: {reason}" for index, reason in failures[:3])
    else:
        note = "; ".join(
            f"hunk {index}: {res.note or res.strategy}" for index, res in pending[:3]
        )

    if pending:
        return FileOutcome(path, False, strategies or ["none"], len(pending), note)

    merged = parsed.render(resolutions)
    if has_conflict_markers(merged):
        return FileOutcome(path, False, strategies, len(blocks), "markers survived resolution")
    ok, reason = _syntax_ok(path, merged)
    if not ok:
        return FileOutcome(path, False, strategies, len(blocks), f"rejected: {reason}")

    full.write_text(merged, encoding="utf-8")
    git_ops.stage(repo_path, [path])
    return FileOutcome(path, True, strategies)


def resolve_conflicts(
    repo_path: Path,
    *,
    provider: LLMProvider | None = None,
    prefer: str | None = None,
    guidance: str = "",
    validation_commands: list[str] | None = None,
    on_event: EventHandler | None = None,
) -> ResolutionResult:
    """Resolve every conflict currently present in the working tree."""

    def emit(kind: str, message: str) -> None:
        if on_event is not None:
            on_event(kind, message)

    git_ops.enable_rerere(repo_path)
    result = ResolutionResult(conflicted=detect_conflicts(repo_path))
    if not result.conflicted:
        emit("conflicts", "No merge conflicts detected.")
        return result

    emit("conflicts", f"Detected {len(result.conflicted)} conflicted file(s).")
    for path in result.conflicted:
        outcome = resolve_file(
            repo_path, path, provider=provider, prefer=prefer, guidance=guidance
        )
        if "llm" in outcome.strategies:
            result.used_llm = True
        result.outcomes.append(outcome)
        emit("conflicts", str(outcome))

    if result.fully_resolved and validation_commands:
        outputs = []
        passed = True
        for command in validation_commands:
            try:
                run = run_command(repo_path, command)
            except CommandNotAllowed as exc:
                outputs.append(f"$ {command}\nskipped: {exc}")
                continue
            outputs.append(f"$ {run.command}\nexit_code: {run.exit_code}\n{run.output[-4000:]}")
            passed = passed and run.ok
            if not run.ok:
                break
        result.validation_output = "\n\n".join(outputs)
        result.validation_passed = passed
        emit("tests", f"Post-merge validation {'passed' if passed else 'FAILED'}.")

    return result


def sync_with_base(
    repo_path: Path,
    base_ref: str,
    *,
    provider: LLMProvider | None = None,
    strategy: str = "merge",
    prefer: str | None = None,
    guidance: str = "",
    validation_commands: list[str] | None = None,
    commit_message: str | None = None,
    abort_on_failure: bool = True,
    on_event: EventHandler | None = None,
) -> ResolutionResult:
    """Bring ``base_ref`` into the current branch, resolving conflicts en route.

    On success the merge/rebase is committed. If anything is left unresolved (or
    post-merge validation fails), the operation is aborted so the branch is left
    exactly as it was.
    """

    def emit(kind: str, message: str) -> None:
        if on_event is not None:
            on_event(kind, message)

    git_ops.enable_rerere(repo_path)
    git_ops.use_diff3_markers(repo_path)

    if git_ops.has_changes(repo_path) and not git_ops.merge_in_progress(repo_path):
        raise RuntimeError(
            "The working tree has uncommitted changes; commit or stash them before syncing."
        )

    emit("merge", f"Bringing {base_ref} into {git_ops.current_branch(repo_path)} via {strategy}.")
    run = (
        git_ops.rebase(repo_path, base_ref)
        if strategy == "rebase"
        else git_ops.merge(repo_path, base_ref)
    )
    if run.ok and not git_ops.conflicted_files(repo_path):
        emit("merge", "Merged cleanly; no conflicts to resolve.")
        return ResolutionResult()

    result = resolve_conflicts(
        repo_path,
        provider=provider,
        prefer=prefer,
        guidance=guidance,
        validation_commands=validation_commands,
        on_event=on_event,
    )

    failed_validation = result.validation_passed is False
    if not result.fully_resolved or failed_validation:
        if abort_on_failure:
            git_ops.abort_merge(repo_path)
            emit(
                "merge",
                "Aborted the merge; the branch is unchanged. "
                + ("Validation failed after resolution." if failed_validation
                   else f"Unresolved: {', '.join(result.unresolved_files)}"),
            )
        return result

    finish = git_ops.continue_merge(
        repo_path,
        commit_message or f"merge: resolve conflicts from {base_ref}",
    )
    result.committed = finish.ok
    emit("merge", "Merge committed." if finish.ok else f"Merge commit failed: {finish.stderr}")
    return result
