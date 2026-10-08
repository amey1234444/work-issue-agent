"""Build the context the LLM sees: repo instructions, file tree and selected files."""

from __future__ import annotations

import glob
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .paths import PathPolicy, PathPolicyError

# Files/dirs that never add useful signal to the model's view of the repo tree.
_IGNORE_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    ".idea",
    ".agent_work",
}

_MAX_FILE_CHARS = 20_000


@dataclass
class RepoContext:
    """Everything we know about the target repo before asking the LLM to act."""

    repo_path: Path
    instructions: dict[str, str] = field(default_factory=dict)
    rules: dict[str, str] = field(default_factory=dict)
    tree: str = ""

    def instructions_block(self) -> str:
        if not self.instructions and not self.rules:
            return "(no instruction files found)"
        parts: list[str] = []
        for name, body in self.instructions.items():
            parts.append(f"===== {name} =====\n{body.strip()}")
        for name, body in self.rules.items():
            parts.append(f"===== rule: {name} =====\n{body.strip()}")
        return "\n\n".join(parts)


def _read_truncated(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if len(text) > _MAX_FILE_CHARS:
        return text[:_MAX_FILE_CHARS] + "\n... [truncated]\n"
    return text


def build_repo_context(
    repo_path: Path, config: Config, policy: PathPolicy | None = None
) -> RepoContext:
    """Collect instruction files, rules and a file tree for the target repo.

    Every file is resolved through the shared :class:`PathPolicy` so instruction
    files cannot be used to pull secrets or out-of-tree content into the prompt.
    """
    policy = policy or PathPolicy(repo_path, protected=tuple(config.protected_paths))
    ctx = RepoContext(repo_path=repo_path)

    for rel in config.instruction_files:
        try:
            fp = policy.resolve(rel)
        except PathPolicyError:
            continue
        if fp.is_file():
            ctx.instructions[rel] = _read_truncated(fp)

    for rule_path in sorted(glob.glob(str(repo_path / config.rules_glob))):
        rp = Path(rule_path)
        try:
            rel_rule = rp.resolve().relative_to(policy.root).as_posix()
            fp = policy.resolve(rel_rule)
        except (ValueError, PathPolicyError):
            continue
        ctx.rules[rp.name] = _read_truncated(fp)

    ctx.tree = build_tree(repo_path, policy=policy)
    return ctx


def build_tree(
    repo_path: Path, max_entries: int = 400, policy: PathPolicy | None = None
) -> str:
    """Return a newline-separated list of tracked-ish files, ignoring noise dirs.

    Prefers ``git ls-files`` when available (respects .gitignore); otherwise walks
    the filesystem. Protected paths are omitted so the model never learns about
    secret files.
    """
    policy = policy or PathPolicy(repo_path)
    files: list[str] = []
    try:
        out = subprocess.run(
            ["git", "ls-files"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        files = [line for line in out.splitlines() if line and not policy.is_protected(line)]
    except (subprocess.CalledProcessError, FileNotFoundError):
        files = []

    if not files:
        for path in sorted(repo_path.rglob("*")):
            if any(part in _IGNORE_DIRS for part in path.parts):
                continue
            if path.is_file():
                rel = path.relative_to(repo_path).as_posix()
                if not policy.is_protected(rel):
                    files.append(rel)
    if len(files) > max_entries:
        return "\n".join(files[:max_entries]) + "\n... [tree truncated]"
    return "\n".join(files)


def read_files(
    repo_path: Path, rel_paths: list[str], policy: PathPolicy | None = None
) -> dict[str, str]:
    """Read a set of repo-relative files, skipping any the path policy rejects."""
    policy = policy or PathPolicy(repo_path)
    result: dict[str, str] = {}
    for rel in rel_paths:
        try:
            fp = policy.resolve(rel)
        except PathPolicyError:
            continue
        if fp.is_file():
            result[rel] = _read_truncated(fp)
    return result
