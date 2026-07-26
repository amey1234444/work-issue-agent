"""Tests for the command allowlist, failure parser and integrity scanner."""

import pytest

from github_issue_agent.validation import anti_cheating
from github_issue_agent.validation.commands import CommandNotAllowed, check_allowed, run
from github_issue_agent.validation.failure_parser import parse_failure

PYTEST_OUTPUT = """============================= test session starts ==============================
collected 3 items

tests/test_x.py::test_a PASSED
tests/test_x.py::test_b FAILED

=================================== FAILURES ===================================
______________________________ test_b _________________________________________
    def test_b():
>       assert add(1, 2) == 4
E       assert 3 == 4
=========================== short test summary info ============================
FAILED tests/test_x.py::test_b - assert 3 == 4
1 failed, 2 passed in 0.10s
"""


def test_check_allowed_accepts_known_tools():
    assert check_allowed("pytest -q") == ["pytest", "-q"]
    assert check_allowed(["python", "-m", "pytest"])[0] == "python"


@pytest.mark.parametrize(
    "command",
    ["curl http://x", "pytest -q && rm -rf /", "git push origin main", "git reset --hard"],
)
def test_check_allowed_rejects_dangerous_commands(command):
    with pytest.raises(CommandNotAllowed):
        check_allowed(command)


def test_check_allowed_honours_extra_allowlist():
    with pytest.raises(CommandNotAllowed):
        check_allowed("bazel build //...")
    assert check_allowed("bazel build //...", extra_allowed=["bazel"])[0] == "bazel"


def test_run_captures_exit_code(tmp_path):
    result = run(tmp_path, ["python", "-c", "import sys; sys.exit(3)"])
    assert result.exit_code == 3
    assert result.ok is False


def test_failure_parser_extracts_failing_tests():
    report = parse_failure("pytest -q", 1, PYTEST_OUTPUT)
    assert report.failure_type in {"assertion_failure", "test_failure"}
    assert "tests/test_x.py::test_b" in report.failing_tests
    rendered = report.as_xml()
    assert "<failing_tests>" in rendered
    # The whole log is never handed back to the model.
    assert len(rendered) < len(PYTEST_OUTPUT) * 2


def test_failure_parser_handles_lint_output():
    report = parse_failure("ruff check .", 1, "app.py:3:1: F401 `os` imported but unused\n")
    assert report.failure_type == "lint_error"
    assert any("F401" in message for message in report.messages)


def test_anti_cheating_flags_test_weakening():
    diff = (
        "--- a/tests/test_x.py\n"
        "+++ b/tests/test_x.py\n"
        "+@pytest.mark.skip(reason='flaky')\n"
        "-    assert add(1, 2) == 3\n"
    )
    reasons = " ".join(finding.reason for finding in anti_cheating.scan_diff(diff))
    assert "skip" in reasons.lower()
    assert "assert" in reasons.lower()
    assert anti_cheating.report(diff)


def test_anti_cheating_quiet_on_honest_diff():
    diff = "--- a/app.py\n+++ b/app.py\n+def add(a, b):\n+    return a + b\n"
    assert anti_cheating.scan_diff(diff) == []
    assert anti_cheating.report(diff) == ""
