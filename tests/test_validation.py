import sys

from github_issue_agent.validation import (
    CheckResult,
    CheckStatus,
    ValidationReport,
    compute_tree_hash,
    plan_checks,
    run_validation,
    skipped_report,
)

PY = sys.executable


def test_plan_checks_required_first_and_dedup():
    planned = plan_checks(["pytest -q", "ruff check ."], ["ruff check .", "  ", "pytest -q -k x"])
    assert planned == [("pytest -q", True), ("ruff check .", True), ("pytest -q -k x", False)]


def test_report_status_rules():
    def rep(*statuses: CheckStatus) -> ValidationReport:
        r = ValidationReport(tree_hash="h")
        r.checks = [CheckResult(f"c{i}", "cmd", True, s, tree_hash="h") for i, s in enumerate(statuses)]
        return r

    assert ValidationReport().status == CheckStatus.NOT_RUN
    assert rep(CheckStatus.PASSED).status == CheckStatus.PASSED
    assert rep(CheckStatus.PASSED, CheckStatus.FAILED).status == CheckStatus.FAILED
    assert rep(CheckStatus.PASSED, CheckStatus.BLOCKED).status == CheckStatus.BLOCKED
    assert rep(CheckStatus.SKIPPED, CheckStatus.SKIPPED).status == CheckStatus.SKIPPED
    assert rep(CheckStatus.PASSED, CheckStatus.SKIPPED).status == CheckStatus.PASSED
    assert rep(CheckStatus.FAILED, CheckStatus.BLOCKED).status == CheckStatus.FAILED
    assert not rep(CheckStatus.FAILED).passed


def test_stale_detection(tmp_path):
    (tmp_path / "a.txt").write_text("1")
    report = run_validation(tmp_path, [(f"{PY} -c 'print(1)'", True)])
    assert report.status == CheckStatus.PASSED
    report.mark_stale_if_changed(compute_tree_hash(tmp_path))
    assert report.status == CheckStatus.PASSED
    (tmp_path / "a.txt").write_text("2")
    report.mark_stale_if_changed(compute_tree_hash(tmp_path))
    assert report.status == CheckStatus.STALE
    assert report.checks[0].status == CheckStatus.STALE
    assert not report.passed


def test_run_validation_records_evidence(tmp_path):
    report = run_validation(
        tmp_path,
        [(f"{PY} -c 'print(\"ok\")'", True), (f"{PY} -c 'raise SystemExit(2)'", False)],
    )
    assert report.status == CheckStatus.FAILED
    ok, bad = report.checks
    assert ok.status == CheckStatus.PASSED and ok.exit_code == 0 and ok.argv[0] == PY
    assert bad.status == CheckStatus.FAILED and bad.exit_code == 2 and bad.required is False
    assert ok.tree_hash == report.tree_hash == compute_tree_hash(tmp_path)
    md = report.evidence_markdown()
    assert "**failed**" in md and "| passed |" in md and "| failed |" in md
    data = report.as_dict()
    assert data["status"] == "failed" and len(data["checks"]) == 2


def test_missing_tool_is_blocked_not_passed(tmp_path):
    report = run_validation(tmp_path, [("no-such-tool-zzz --version", True)])
    assert report.status == CheckStatus.BLOCKED
    assert not report.passed


def test_skipped_report():
    report = skipped_report([("pytest -q", True)], tree_hash="h")
    assert report.status == CheckStatus.SKIPPED
    assert not report.passed


def test_tree_hash_ignores_git_internals_and_tracks_content(tmp_path):
    (tmp_path / "f.txt").write_text("a")
    h1 = compute_tree_hash(tmp_path)
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "index").write_text("junk")
    assert compute_tree_hash(tmp_path) == h1
    (tmp_path / "f.txt").write_text("b")
    assert compute_tree_hash(tmp_path) != h1
