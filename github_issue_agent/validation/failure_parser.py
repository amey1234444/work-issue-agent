"""Turn a huge test/lint log into a small, focused failure report.

Sending 50k lines of CI output back to the model wastes context and buries the
signal. We extract the failing tests, the assertion message and a bounded slice
of traceback, and expose the rest through ``read_command_output``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_PYTEST_FAIL_RE = re.compile(r"^(FAILED|ERROR)\s+(?P<test>\S+)", re.MULTILINE)
_PYTEST_SHORT_RE = re.compile(r"^(?P<test>\S+::\S+)\s+-\s+(?P<message>.+)$", re.MULTILINE)
_JEST_FAIL_RE = re.compile(r"^\s*(?:✕|×|✖)\s+(?P<test>.+)$", re.MULTILINE)
_GO_FAIL_RE = re.compile(r"^---\s+FAIL:\s+(?P<test>\S+)", re.MULTILINE)
_CARGO_FAIL_RE = re.compile(r"^test\s+(?P<test>\S+)\s+\.\.\.\s+FAILED", re.MULTILINE)
_RUFF_RE = re.compile(r"^(?P<loc>[\w./\\-]+:\d+:\d+):\s+(?P<code>[A-Z]+\d+)\s+(?P<msg>.+)$", re.M)
_MYPY_RE = re.compile(r"^(?P<loc>[\w./\\-]+:\d+):\s+error:\s+(?P<msg>.+)$", re.MULTILINE)
_TRACEBACK_RE = re.compile(r"Traceback \(most recent call last\):")
_ASSERTION_RE = re.compile(r"^E\s+(?P<msg>.+)$", re.MULTILINE)

_MAX_TRACEBACK_LINES = 60


@dataclass
class FailureReport:
    command: str
    exit_code: int
    failure_type: str = "unknown"
    failing_tests: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    traceback: str = ""
    total_lines: int = 0
    command_id: str = ""

    def as_xml(self) -> str:
        tests = "\n".join(f"    {t}" for t in self.failing_tests[:10]) or "    (none identified)"
        messages = "\n".join(f"    {m}" for m in self.messages[:10]) or "    (none captured)"
        parts = [
            "<validation_result>",
            f"  <command>{self.command}</command>",
            f"  <exit_code>{self.exit_code}</exit_code>",
            f"  <failure_type>{self.failure_type}</failure_type>",
            "  <failing_tests>",
            tests,
            "  </failing_tests>",
            "  <messages>",
            messages,
            "  </messages>",
        ]
        if self.traceback:
            parts += ["  <traceback>", self.traceback, "  </traceback>"]
        if self.command_id:
            parts.append(
                f"  <full_log lines=\"{self.total_lines}\">"
                f"read_command_output(command_id={self.command_id!r}, start_line=1)"
                "</full_log>"
            )
        parts.append("</validation_result>")
        return "\n".join(parts)


def _tail_traceback(output: str) -> str:
    matches = list(_TRACEBACK_RE.finditer(output))
    if not matches:
        return ""
    tail = output[matches[-1].start() :].splitlines()[:_MAX_TRACEBACK_LINES]
    return "\n".join(f"    {line}" for line in tail)


def parse_failure(command: str, exit_code: int, output: str, command_id: str = "") -> FailureReport:
    """Extract the actionable part of a failed command's output."""
    report = FailureReport(
        command=command,
        exit_code=exit_code,
        total_lines=len(output.splitlines()),
        command_id=command_id,
    )
    if exit_code == 124:
        report.failure_type = "timeout"
        report.messages = [output.strip()[:500]]
        return report

    for pattern in (_PYTEST_FAIL_RE, _JEST_FAIL_RE, _GO_FAIL_RE, _CARGO_FAIL_RE):
        report.failing_tests.extend(m.group("test").strip() for m in pattern.finditer(output))
    report.failing_tests = list(dict.fromkeys(report.failing_tests))[:20]

    lint_hits = [f"{m['loc']} {m['code']} {m['msg']}" for m in _RUFF_RE.finditer(output)]
    type_hits = [f"{m['loc']} {m['msg']}" for m in _MYPY_RE.finditer(output)]
    assertions = [m.group("msg").strip() for m in _ASSERTION_RE.finditer(output)]
    short = [f"{m['test']} - {m['message']}" for m in _PYTEST_SHORT_RE.finditer(output)]

    if report.failing_tests:
        report.failure_type = "assertion_failure" if assertions else "test_failure"
        report.messages = (assertions or short)[:10]
        report.traceback = _tail_traceback(output)
    elif type_hits:
        report.failure_type = "type_error"
        report.messages = type_hits[:10]
    elif lint_hits:
        report.failure_type = "lint_error"
        report.messages = lint_hits[:10]
    elif "SyntaxError" in output or "IndentationError" in output:
        report.failure_type = "syntax_error"
        report.messages = [
            line.strip() for line in output.splitlines() if "Error" in line
        ][:10]
        report.traceback = _tail_traceback(output)
    else:
        report.failure_type = "command_error"
        tail = output.strip().splitlines()[-25:]
        report.messages = [line.strip() for line in tail if line.strip()][:10]

    return report


def summarise(command: str, exit_code: int, output: str, command_id: str = "") -> str:
    """Convenience helper returning the XML report for a failed command."""
    return parse_failure(command, exit_code, output, command_id).as_xml()
