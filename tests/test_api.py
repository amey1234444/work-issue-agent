import os
from pathlib import Path

import pytest

from github_issue_agent import WorkflowResult, run_workflow, work_issue
from github_issue_agent.api import AgentError, _apply_overrides, authed_remote
from github_issue_agent.config import Config

WORKFLOW = "# Workflow: Work Issue\n\nResolve the issue and add a note.\n"


def _make_repo(tmp_path: Path) -> Path:
    wf = tmp_path / ".ai" / "workflows"
    wf.mkdir(parents=True)
    (wf / "work-issue.md").write_text(WORKFLOW, encoding="utf-8")
    return tmp_path


def test_run_workflow_mock_no_pr(tmp_path):
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
    assert result.tests_passed is True
    assert result.pr_url is None
    # The mock provider creates AGENT_NOTES.md.
    assert any("AGENT_NOTES.md" in f for f in result.changed_files)
    assert (repo / "AGENT_NOTES.md").exists()
    # Agent mode is the default: it works through tool calls, not a single plan.
    assert result.mode == "agent"
    assert any(kind == "tool" for kind, _ in events)
    assert any(call.startswith("apply_patch") for call in result.tool_calls)


def test_run_workflow_legacy_mode_still_plans(tmp_path):
    repo = _make_repo(tmp_path)
    events: list[tuple[str, str]] = []
    result = run_workflow(
        "work-issue",
        repo_path=repo,
        prompt="Add a note about contributing.",
        provider="mock",
        mode="workflow",
        open_pr=False,
        on_event=lambda k, m: events.append((k, m)),
    )
    assert result.mode == "workflow"
    assert (repo / "AGENT_NOTES.md").exists()
    assert any(kind == "plan" for kind, _ in events)


def test_run_workflow_dry_run_makes_no_edits(tmp_path):
    repo = _make_repo(tmp_path)
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
    assert not (repo / "AGENT_NOTES.md").exists()


def test_run_workflow_unknown_workflow_raises(tmp_path):
    repo = _make_repo(tmp_path)
    with pytest.raises(AgentError):
        run_workflow("does-not-exist", repo_path=repo, prompt="x", provider="mock", open_pr=False)


def test_work_issue_requires_task(tmp_path):
    repo = _make_repo(tmp_path)
    # No issue (mock can't fetch) and no prompt -> build_task raises -> AgentError.
    with pytest.raises(AgentError):
        run_workflow("work-issue", repo_path=repo, provider="mock", open_pr=False)


def test_apply_overrides_routes_model_and_api_key(monkeypatch):
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
    assert os.environ["OPENROUTER_API_KEY"] == "sk-or-test"


def test_authed_remote_injects_token_once():
    url = "https://github.com/org/repo.git"
    assert authed_remote(url, "tok") == "https://x-access-token:tok@github.com/org/repo.git"
    # Already-authed URLs are left untouched.
    already = "https://x-access-token:tok@github.com/org/repo.git"
    assert authed_remote(already, "other") == already


def test_work_issue_is_run_workflow_wrapper(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    captured = {}

    def fake_run_workflow(workflow, **kwargs):
        captured["workflow"] = workflow
        captured["kwargs"] = kwargs
        return WorkflowResult(workflow=workflow, tests_passed=True)

    monkeypatch.setattr("github_issue_agent.api.run_workflow", fake_run_workflow)
    work_issue("https://github.com/o/r/issues/1", repo_path=repo, provider="mock")
    assert captured["workflow"] == "work-issue"
    assert captured["kwargs"]["issue_url"] == "https://github.com/o/r/issues/1"
