import os
import subprocess
import sys
from pathlib import Path

import pytest

from github_issue_agent import CheckStatus, WorkflowResult, run_workflow, work_issue
from github_issue_agent.api import AgentError, _apply_overrides
from github_issue_agent.config import Config

WORKFLOW = "# Workflow: Work Issue\n\nResolve the issue and add a note.\n"


def _make_repo(tmp_path: Path, config: str = "") -> Path:
    wf = tmp_path / ".ai" / "workflows"
    wf.mkdir(parents=True)
    (wf / "work-issue.md").write_text(WORKFLOW, encoding="utf-8")
    if config:
        (tmp_path / ".ai" / "config.yaml").write_text(config, encoding="utf-8")
    return tmp_path


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def _make_git_repo(tmp_path: Path, config: str = "") -> Path:
    repo = _make_repo(tmp_path, config)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def test_run_workflow_mock_no_pr_without_checks_is_not_validated(tmp_path):
    repo = _make_repo(tmp_path)
    events: list[tuple[str, str]] = []
    result = run_workflow(
        "work-issue",
        repo_path=repo,
        prompt="Add a note about contributing.",
        provider="mock",
        open_pr=False,
        on_event=lambda k, m: events.append((k, m)),
    )
    assert isinstance(result, WorkflowResult)
    # No checks configured -> validation is *not_run*, never silently "passed".
    assert result.validation.status == CheckStatus.NOT_RUN
    assert result.tests_passed is False
    assert result.status == "unvalidated"
    assert result.pr_url is None
    assert any("AGENT_NOTES.md" in f for f in result.changed_files)
    assert (repo / "AGENT_NOTES.md").exists()
    assert any(kind == "plan" for kind, _ in events)
    assert result.run_id


def test_run_workflow_with_passing_check_is_validated(tmp_path):
    repo = _make_repo(tmp_path, f"provider: mock\ntest_command: {sys.executable} -c 'print(1)'\n")
    result = run_workflow("work-issue", repo_path=repo, prompt="x", provider="mock", open_pr=False)
    assert result.validation.status == CheckStatus.PASSED
    assert result.tests_passed is True
    assert result.status == "validated"
    check = result.validation.checks[0]
    assert check.required is True
    assert check.exit_code == 0
    assert check.tree_hash == result.validation.tree_hash


def test_failing_required_check_blocks_pr(tmp_path, monkeypatch):
    repo = _make_git_repo(tmp_path, f"provider: mock\ntest_command: {sys.executable} -c 'raise SystemExit(3)'\n")
    _git(repo, "remote", "add", "origin", "https://github.com/o/r.git")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    with pytest.raises(AgentError) as ei:
        run_workflow("work-issue", repo_path=repo, prompt="x", provider="mock", open_pr=True)
    assert ei.value.code == "validation"
    assert ei.value.exit_code == 1
    assert "failed" in str(ei.value)
    # Developer checkout untouched; work lives in an isolated worktree.
    assert not (repo / "AGENT_NOTES.md").exists()
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert _git(repo, "status", "--porcelain") == ""


def test_isolated_run_preserves_dirty_checkout(tmp_path):
    repo = _make_git_repo(tmp_path, f"provider: mock\ntest_command: {sys.executable} -c 'print(1)'\n")
    (repo / "scratch.txt").write_text("wip", encoding="utf-8")
    (repo / "AGENT_NOTES.md").write_text("mine", encoding="utf-8")
    result = run_workflow("work-issue", repo_path=repo, prompt="x", provider="mock", open_pr=False)
    assert result.workspace is not None and Path(result.workspace).is_dir()
    assert (Path(result.workspace) / "AGENT_NOTES.md").read_text(encoding="utf-8") != "mine"
    assert (repo / "AGENT_NOTES.md").read_text(encoding="utf-8") == "mine"
    assert (repo / "scratch.txt").read_text(encoding="utf-8") == "wip"
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"


def test_run_workflow_dry_run_makes_no_edits(tmp_path):
    repo = _make_git_repo(tmp_path, f"provider: mock\ntest_command: {sys.executable} -c 'print(1)'\n")
    result = run_workflow(
        "work-issue",
        repo_path=repo,
        prompt="Do something.",
        provider="mock",
        dry_run=True,
        open_pr=False,
    )
    assert result.dry_run is True
    assert result.changed_files == []
    assert result.validation.status == CheckStatus.SKIPPED
    assert not (repo / "AGENT_NOTES.md").exists()
    assert not any(p.is_dir() for p in (repo / ".agent_work").iterdir())
    assert "agent/run-" not in _git(repo, "branch", "--list")


def test_run_workflow_unknown_workflow_raises(tmp_path):
    repo = _make_repo(tmp_path)
    with pytest.raises(AgentError) as ei:
        run_workflow("does-not-exist", repo_path=repo, prompt="x", provider="mock", open_pr=False)
    assert ei.value.code == "configuration"


def test_work_issue_requires_task(tmp_path):
    repo = _make_repo(tmp_path)
    with pytest.raises(AgentError):
        run_workflow("work-issue", repo_path=repo, provider="mock", open_pr=False)


def test_apply_overrides_routes_model_and_api_key_without_env_mutation(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    cfg = Config()
    _apply_overrides(
        cfg,
        provider="openrouter",
        model="vendor/model:free",
        api_key="sk-or-test",
        github_token="ghp_test",
        max_iterations=5,
    )
    assert cfg.provider == "openrouter"
    assert cfg.openrouter_model == "vendor/model:free"
    assert cfg.github_token == "ghp_test"
    assert cfg.max_iterations == 5
    assert cfg.resolve_api_key() == "sk-or-test"
    assert "OPENROUTER_API_KEY" not in os.environ


def test_apply_overrides_validates(monkeypatch):
    cfg = Config()
    with pytest.raises(AgentError) as ei:
        _apply_overrides(cfg, provider="nope", model=None, api_key=None, github_token=None, max_iterations=None)
    assert ei.value.code == "configuration"


def test_work_issue_is_run_workflow_wrapper(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    captured = {}

    def fake_run_workflow(workflow, **kwargs):
        captured["workflow"] = workflow
        captured["kwargs"] = kwargs
        return WorkflowResult(workflow=workflow)

    monkeypatch.setattr("github_issue_agent.api.run_workflow", fake_run_workflow)
    work_issue("https://github.com/o/r/issues/1", repo_path=repo, provider="mock")
    assert captured["workflow"] == "work-issue"
    assert captured["kwargs"]["issue_url"] == "https://github.com/o/r/issues/1"


def test_result_as_dict_is_json_friendly():
    import json

    data = WorkflowResult(workflow="w", run_id="r").as_dict()
    json.dumps(data)
    assert data["validation"]["status"] == "not_run"
