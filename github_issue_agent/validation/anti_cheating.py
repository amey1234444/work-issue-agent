"""Detect changes that make validation pass without solving the problem.

The classic failure mode of an autonomous coding agent is "make the suite
green": deleting assertions, adding skip markers, or widening lint ignores. We
scan the final diff for those patterns and surface them, both to the model
(so it can fix itself) and to the PR body (so a human can see them).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_TEST_PATH_RE = re.compile(r"(^|/)(tests?|spec|__tests__)/|(^|/)test_[^/]+\.py$|\.(test|spec)\.[jt]sx?$")

_SUSPICIOUS_ADDITIONS = [
    (re.compile(r"@(?:pytest\.mark\.)?(?:skip|xfail)\b"), "adds a skip/xfail marker to a test"),
    (re.compile(r"\b(?:it|test|describe)\.(?:skip|todo)\("), "skips a JS/TS test"),
    (re.compile(r"#\s*type:\s*ignore(?!\[)"), "adds a blanket 'type: ignore'"),
    (re.compile(r"#\s*noqa(?!:)"), "adds a blanket '# noqa'"),
    (re.compile(r"eslint-disable(?!-next-line\s+\S)"), "adds a blanket eslint-disable"),
    (re.compile(r"--no-verify"), "bypasses git hooks"),
    (re.compile(r"\bcontinue-on-error:\s*true"), "makes a CI step non-blocking"),
    (re.compile(r"\bexit\s+0\b.*#.*(?:test|lint)"), "forces a success exit code"),
]

_ASSERTION_RE = re.compile(r"^\s*(assert\b|expect\(|self\.assert|require\.|t\.Error)")


@dataclass
class Finding:
    path: str
    reason: str
    line: str

    def __str__(self) -> str:
        return f"{self.path}: {self.reason} -> {self.line.strip()[:120]}"


def _iter_diff_files(diff: str):
    path = ""
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:].strip()
        yield path, line


def scan_diff(diff: str) -> list[Finding]:
    """Return suspicious edits found in a unified diff."""
    findings: list[Finding] = []
    removed_assertions: dict[str, int] = {}
    deleted_test_files: list[str] = []

    current = ""
    for line in diff.splitlines():
        if line.startswith("--- a/"):
            current = line[6:].strip()
        elif line.startswith("+++ "):
            new_path = line[4:].strip()
            if new_path == "/dev/null" and _TEST_PATH_RE.search(current):
                deleted_test_files.append(current)
            elif new_path.startswith("b/"):
                current = new_path[2:]
        elif line.startswith("+") and not line.startswith("+++"):
            body = line[1:]
            for pattern, reason in _SUSPICIOUS_ADDITIONS:
                if pattern.search(body):
                    findings.append(Finding(current, reason, body))
        elif line.startswith("-") and not line.startswith("---"):
            body = line[1:]
            if _TEST_PATH_RE.search(current) and _ASSERTION_RE.search(body):
                removed_assertions[current] = removed_assertions.get(current, 0) + 1

    for path, count in removed_assertions.items():
        findings.append(
            Finding(path, f"removes {count} assertion(s) from a test file", "")
        )
    for path in deleted_test_files:
        findings.append(Finding(path, "deletes an entire test file", ""))
    return findings


def report(diff: str) -> str:
    """Human/model-readable integrity report for a diff ('' when clean)."""
    findings = scan_diff(diff)
    if not findings:
        return ""
    lines = ["<integrity_warnings>"]
    lines += [f"  - {f}" for f in findings]
    lines.append(
        "  Weakening tests or suppressing checks is not an acceptable resolution. "
        "Revert these unless the issue explicitly asked for them, and justify any "
        "you keep."
    )
    lines.append("</integrity_warnings>")
    return "\n".join(lines)
