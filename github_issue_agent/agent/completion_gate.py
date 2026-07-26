"""The "done when" contract: parse the final report and verify the claims.

The model does not get to declare victory on its own. We parse its structured
report, then check that it actually changed something, actually ran validation,
and did not weaken the tests.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..validation.anti_cheating import scan_diff

_FIELD_RE = {
    "summary": re.compile(r"^SUMMARY:\s*(?P<value>.+?)\s*$", re.MULTILINE),
    "branch": re.compile(r"^BRANCH:\s*(?P<value>.+?)\s*$", re.MULTILINE),
    "commit_message": re.compile(r"^COMMIT:\s*(?P<value>.+?)\s*$", re.MULTILINE),
    "pr_title": re.compile(r"^PR_TITLE:\s*(?P<value>.+?)\s*$", re.MULTILINE),
}
_PR_BODY_RE = re.compile(r"^PR_BODY:\s*\n?(?P<value>.*?)(?=^\s*VALIDATION:|\Z)", re.MULTILINE | re.DOTALL)
_VALIDATION_RE = re.compile(r"^VALIDATION:\s*(?P<value>.*)\Z", re.MULTILINE | re.DOTALL)
_BRANCH_SAFE_RE = re.compile(r"[^a-z0-9._/-]+")


@dataclass
class FinalReport:
    """The model's structured wrap-up, with sane fallbacks."""

    summary: str = ""
    branch: str = "agent/change"
    commit_message: str = "agent: apply changes"
    pr_title: str = "Changes by work-issue-agent"
    pr_body: str = ""
    validation: str = ""
    raw: str = ""


def sanitise_branch(name: str) -> str:
    cleaned = _BRANCH_SAFE_RE.sub("-", name.strip().lower()).strip("-/.")
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    return cleaned[:60] or "agent/change"


def parse_final_report(text: str) -> FinalReport:
    report = FinalReport(raw=text)
    for attribute, pattern in _FIELD_RE.items():
        match = pattern.search(text)
        if match:
            setattr(report, attribute, match.group("value").strip())
    body = _PR_BODY_RE.search(text)
    if body:
        report.pr_body = body.group("value").strip()
    validation = _VALIDATION_RE.search(text)
    if validation:
        report.validation = validation.group("value").strip()
    if not report.summary:
        report.summary = text.strip().splitlines()[0][:300] if text.strip() else ""
    if not report.pr_body:
        report.pr_body = report.summary
    report.branch = sanitise_branch(report.branch)
    return report


@dataclass
class GateResult:
    """Whether the run may finish, and what still needs doing if not."""

    passed: bool
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_feedback(self) -> str:
        lines = ["<completion_gate status=\"rejected\">"]
        lines += [f"  - {p}" for p in self.problems]
        lines += [f"  - warning: {w}" for w in self.warnings]
        lines.append("  Address these, then produce the final report again.")
        lines.append("</completion_gate>")
        return "\n".join(lines)


def check_completion(
    *,
    diff: str,
    validation_runs: list[tuple[str, bool]],
    require_validation: bool = True,
    require_changes: bool = True,
) -> GateResult:
    """Verify the run's evidence before allowing it to finish.

    ``validation_runs`` is ``[(command, passed), ...]`` for every run_command
    call the loop observed.
    """
    problems: list[str] = []
    warnings: list[str] = []

    if require_changes and not diff.strip():
        problems.append("No file changes were made; the task cannot be complete.")

    validating = [
        (command, ok)
        for command, ok in validation_runs
        if re.search(r"\b(pytest|test|tox|nox|ruff|mypy|lint|eslint|tsc|vitest|jest|cargo|go)\b", command)
    ]
    if require_validation and not validating:
        problems.append(
            "No test, lint or type-check command was run. Run the repository's "
            "validation commands with run_command before finishing."
        )
    failing = [command for command, ok in validating if not ok]
    if failing:
        last_status = {command: ok for command, ok in validating}
        still_failing = [command for command in failing if not last_status.get(command, False)]
        if still_failing:
            problems.append(
                "These validation commands are still failing: " + "; ".join(sorted(set(still_failing)))
            )

    for finding in scan_diff(diff):
        warnings.append(str(finding))

    return GateResult(passed=not problems, problems=problems, warnings=warnings)
