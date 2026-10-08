"""Deterministic validation service: required checks, evidence and statuses.

A run is only "validated" when every *required* check (configured by the
repository, not chosen by the model) ran successfully against the exact tree
that is being published. Each check records argv, exit code, timing and the
workspace tree hash it ran on; any later edit marks that evidence ``stale``.

Statuses:

``passed``    every required check ran and exited 0 on the current tree
``failed``    a check exited non-zero
``not_run``   no checks were configured or requested
``skipped``   checks were configured but deliberately not executed (dry run)
``blocked``   checks could not be executed (cancel, deadline, missing tool)
``stale``     the tree changed after the checks ran
"""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .runner import CancellationToken, CommandResult, Deadline, run_all


class CheckStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    NOT_RUN = "not_run"
    SKIPPED = "skipped"
    BLOCKED = "blocked"
    STALE = "stale"


@dataclass
class CheckResult:
    check_id: str
    command: str
    required: bool
    status: CheckStatus
    exit_code: int | None = None
    output: str = ""
    argv: list[str] = field(default_factory=list)
    duration: float = 0.0
    tree_hash: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "check_id": self.check_id,
            "command": self.command,
            "required": self.required,
            "status": self.status.value,
            "exit_code": self.exit_code,
            "duration_seconds": round(self.duration, 3),
            "tree_hash": self.tree_hash,
            "output_tail": self.output[-2000:],
        }


@dataclass
class ValidationReport:
    """Evidence for one validation pass over a specific tree."""

    tree_hash: str = ""
    checks: list[CheckResult] = field(default_factory=list)
    stale: bool = False

    @property
    def status(self) -> CheckStatus:
        if self.stale:
            return CheckStatus.STALE
        if not self.checks:
            return CheckStatus.NOT_RUN
        statuses = [c.status for c in self.checks]
        if CheckStatus.FAILED in statuses:
            return CheckStatus.FAILED
        if CheckStatus.BLOCKED in statuses:
            return CheckStatus.BLOCKED
        if all(s == CheckStatus.SKIPPED for s in statuses):
            return CheckStatus.SKIPPED
        if all(s in (CheckStatus.PASSED, CheckStatus.SKIPPED) for s in statuses) and any(
            s == CheckStatus.PASSED for s in statuses
        ):
            return CheckStatus.PASSED
        return CheckStatus.NOT_RUN

    @property
    def passed(self) -> bool:
        return self.status == CheckStatus.PASSED

    @property
    def output(self) -> str:
        return "\n\n".join(f"$ {c.command}\n{c.output}" for c in self.checks if c.output)

    def mark_stale_if_changed(self, current_tree_hash: str) -> None:
        if self.checks and self.tree_hash and self.tree_hash != current_tree_hash:
            self.stale = True
            for c in self.checks:
                if c.status == CheckStatus.PASSED:
                    c.status = CheckStatus.STALE

    def evidence_markdown(self) -> str:
        if not self.checks:
            return f"Validation: **{self.status.value}** (no checks were run)."
        lines = [f"Validation: **{self.status.value}** on tree `{self.tree_hash[:12]}`", ""]
        lines.append("| Check | Required | Status | Exit | Duration |")
        lines.append("|---|---|---|---|---|")
        for c in self.checks:
            req = "yes" if c.required else "no"
            code = "-" if c.exit_code is None else str(c.exit_code)
            lines.append(f"| `{c.command}` | {req} | {c.status.value} | {code} | {c.duration:.1f}s |")
        return "\n".join(lines)

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "tree_hash": self.tree_hash,
            "stale": self.stale,
            "checks": [c.as_dict() for c in self.checks],
        }


def compute_tree_hash(repo_path: Path) -> str:
    """Hash of the working tree contents (tracked + untracked, minus ignored)."""
    try:
        listing = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=repo_path,
            capture_output=True,
            check=True,
        ).stdout
        files = sorted(p.decode("utf-8", "surrogateescape") for p in listing.split(b"\0") if p)
    except (subprocess.CalledProcessError, FileNotFoundError):
        files = sorted(
            str(p.relative_to(repo_path)).replace("\\", "/")
            for p in repo_path.rglob("*")
            if p.is_file() and ".git" not in p.parts and ".agent_work" not in p.parts
        )
    h = hashlib.sha256()
    for rel in files:
        fp = repo_path / rel
        if not fp.is_file():
            continue
        h.update(rel.encode("utf-8", "surrogateescape"))
        h.update(b"\0")
        h.update(hashlib.sha256(fp.read_bytes()).digest())
    return h.hexdigest()


def plan_checks(required: list[str], suggested: list[str]) -> list[tuple[str, bool]]:
    """Merge repository-required checks with model-suggested extras.

    Required checks always come first and cannot be removed or reordered by the
    model. Suggested commands that duplicate a required one are dropped.
    """
    planned: list[tuple[str, bool]] = [(c, True) for c in required]
    seen = {c for c in required}
    for cmd in suggested:
        cmd = cmd.strip()
        if cmd and cmd not in seen:
            planned.append((cmd, False))
            seen.add(cmd)
    return planned


def run_validation(
    repo_path: Path,
    planned: list[tuple[str, bool]],
    *,
    timeout: float = 1800,
    max_output_chars: int = 200_000,
    cancel: CancellationToken | None = None,
    deadline: Deadline | None = None,
    on_start: Callable[[str], None] | None = None,
) -> ValidationReport:
    """Execute the planned checks against the current tree and return evidence."""
    tree_hash = compute_tree_hash(repo_path)
    report = ValidationReport(tree_hash=tree_hash)
    if not planned:
        return report

    commands = [cmd for cmd, _ in planned]
    results: list[CommandResult] = run_all(
        repo_path,
        commands,
        timeout=timeout,
        max_output_chars=max_output_chars,
        cancel=cancel,
        deadline=deadline,
        on_start=on_start,
    )
    by_cmd = {r.command: r for r in results}
    for idx, (cmd, required) in enumerate(planned):
        res = by_cmd.get(cmd)
        check_id = f"check-{idx + 1}"
        if res is None:
            status = CheckStatus.BLOCKED
            report.checks.append(
                CheckResult(check_id, cmd, required, status, None, "Not executed.", [], 0.0, tree_hash)
            )
            continue
        if res.exit_code in (124, 130, 126, 127):
            status = CheckStatus.BLOCKED
        elif res.ok:
            status = CheckStatus.PASSED
        else:
            status = CheckStatus.FAILED
        report.checks.append(
            CheckResult(
                check_id,
                cmd,
                required,
                status,
                res.exit_code,
                res.output,
                res.argv,
                res.duration,
                tree_hash,
            )
        )
    return report


def skipped_report(planned: list[tuple[str, bool]], tree_hash: str = "") -> ValidationReport:
    report = ValidationReport(tree_hash=tree_hash)
    for idx, (cmd, required) in enumerate(planned):
        report.checks.append(
            CheckResult(f"check-{idx + 1}", cmd, required, CheckStatus.SKIPPED, tree_hash=tree_hash)
        )
    return report
