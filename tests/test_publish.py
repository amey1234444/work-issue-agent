"""End-to-end publication tests against a local bare git remote with a fake GitHub API."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from github_issue_agent import CheckStatus, run_workflow
from github_issue_agent import api as api_mod
from github_issue_agent.api import AgentError
from github_issue_agent.github_client import GitHubClient

PY = sys.executable
WORKFLOW = "# Workflow: Work Issue\n\nResolve the issue and add a note.\n"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


class FakeGitHub:
    """Stands in for GitHubClient; records PR creations."""

    created: list[dict[str, object]] = []
    existing: dict[tuple[str, str], str] = {}

    def __init__(self, token, **_):
        assert token
        self.token = token

    parse_issue_url = staticmethod(GitHubClient.parse_issue_url)

    @staticmethod
    def parse_repo_url(url):
        if url.startswith("https://github.com/"):
            return GitHubClient.parse_repo_url(url)
        return "o", "r"  # local bare remote used by the tests

    def default_branch(self, owner, repo):
        return "main"

    def find_pull_request(self, owner, repo, head, base):
        return FakeGitHub.existing.get((head, base))

    def create_pull_request(self, owner, repo, title, head, base, body, *, draft=False):
        found = self.find_pull_request(owner, repo, head, base)
        if found:
            return found
        url = f"https://github.com/{owner}/{repo}/pull/{len(FakeGitHub.created) + 1}"
        FakeGitHub.created.append(
            {"title": title, "head": head, "base": base, "body": body, "draft": draft, "url": url}
        )
        FakeGitHub.existing[(head, base)] = url
        return url


@pytest.fixture
def fake_gh(monkeypatch):
    FakeGitHub.created = []
    FakeGitHub.existing = {}
    monkeypatch.setattr(api_mod, "GitHubClient", FakeGitHub)
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    return FakeGitHub


@pytest.fixture
def repo_with_remote(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", str(remote))
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".ai" / "workflows").mkdir(parents=True)
    (repo / ".ai" / "workflows" / "work-issue.md").write_text(WORKFLOW, encoding="utf-8")
    (repo / ".ai" / "config.yaml").write_text(
        f"provider: mock\ntest_command: {PY} -c 'print(1)'\nchecks:\n  - {PY} -c 'print(2)'\n",
        encoding="utf-8",
    )
    (repo / "README.md").write_text("hi\n", encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-q", "-u", "origin", "main")
    return repo, remote


def test_publish_happy_path_scoped_staging_and_evidence(repo_with_remote, fake_gh):
    repo, remote = repo_with_remote
    (repo / "untracked-wip.txt").write_text("do not commit me", encoding="utf-8")
    (repo / "README.md").write_text("dirty\n", encoding="utf-8")

    result = run_workflow("work-issue", repo_path=repo, prompt="x", provider="mock", open_pr=True)

    assert result.status == "published"
    assert result.pr_url and result.pr_url.startswith("https://github.com/")
    assert result.validation.status == CheckStatus.PASSED
    assert result.branch and result.branch.startswith("agent/")
    assert result.branch != "main"

    # Only the agent's manifest was committed, on the pushed branch.
    files = _git(remote, "ls-tree", "-r", "--name-only", result.branch).splitlines()
    assert "AGENT_NOTES.md" in files
    assert "untracked-wip.txt" not in files
    assert _git(remote, "show", f"{result.branch}:README.md") == "hi"

    # Developer checkout untouched, worktree cleaned up, no token persisted.
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert (repo / "README.md").read_text(encoding="utf-8") == "dirty\n"
    assert (repo / "untracked-wip.txt").exists()
    assert not (repo / "AGENT_NOTES.md").exists()
    assert not any(p.is_dir() for p in (repo / ".agent_work").iterdir())
    assert "ghp_test" not in (repo / ".git" / "config").read_text(encoding="utf-8")
    assert _git(repo, "remote", "get-url", "origin") == str(remote)

    pr = fake_gh.created[-1]
    assert pr["draft"] is True
    body = str(pr["body"])
    assert "Validation: **passed**" in body
    assert "print(1)" in body and "print(2)" in body
    assert result.validation.tree_hash[:12] in body


def test_publish_is_idempotent_when_pr_exists(repo_with_remote, fake_gh):
    repo, _ = repo_with_remote
    first = run_workflow(
        "work-issue", repo_path=repo, prompt="x", provider="mock", open_pr=True, run_id="r1"
    )
    assert len(fake_gh.created) == 1
    # A second run picks a non-colliding branch and its own PR ...
    second = run_workflow(
        "work-issue", repo_path=repo, prompt="x", provider="mock", open_pr=True, run_id="r2"
    )
    assert second.branch != first.branch
    assert len(fake_gh.created) == 2
    # ... while re-creating for an existing head/base returns the same PR instead of failing.
    gh = fake_gh("tok")
    assert gh.create_pull_request("o", "r", "t", first.branch, "main", "b") == first.pr_url
    assert len(fake_gh.created) == 2


def test_stale_evidence_blocks_publication(repo_with_remote, fake_gh, monkeypatch):
    repo, _ = repo_with_remote
    real_run_validation = api_mod.run_validation

    def sneaky_validation(ws_path, planned, **kw):
        report = real_run_validation(ws_path, planned, **kw)
        # Simulate something (formatter, hook) mutating the tree after checks ran.
        (Path(ws_path) / "AGENT_NOTES.md").write_text("mutated after validation\n", encoding="utf-8")
        return report

    monkeypatch.setattr(api_mod, "run_validation", sneaky_validation)
    with pytest.raises(AgentError) as ei:
        run_workflow("work-issue", repo_path=repo, prompt="x", provider="mock", open_pr=True)
    assert ei.value.code == "validation"
    assert "'stale'" in str(ei.value)
    assert fake_gh.created == []


def test_no_checks_configured_blocks_publication(repo_with_remote, fake_gh):
    repo, _ = repo_with_remote
    (repo / ".ai" / "config.yaml").write_text("provider: mock\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "drop checks")
    with pytest.raises(AgentError) as ei:
        run_workflow("work-issue", repo_path=repo, prompt="x", provider="mock", open_pr=True)
    assert ei.value.code == "validation"
    assert "'not_run'" in str(ei.value)
    assert "Configure test_command" in ei.value.recovery
    assert fake_gh.created == []

    # Explicit opt-out publishes but the evidence still says not_run.
    result = run_workflow(
        "work-issue", repo_path=repo, prompt="x", provider="mock", open_pr=True, allow_unvalidated=True
    )
    assert result.status == "published"
    assert "Validation: **not_run**" in str(fake_gh.created[-1]["body"])


def test_model_commands_cannot_replace_required_checks(repo_with_remote, fake_gh, monkeypatch):
    repo, _ = repo_with_remote
    (repo / ".ai" / "config.yaml").write_text(
        f"provider: mock\ntest_command: {PY} -c 'raise SystemExit(1)'\n", encoding="utf-8"
    )
    _git(repo, "commit", "-q", "-am", "failing check")
    from github_issue_agent import llm

    class ChattyMock(llm.MockProvider):
        def complete(self, system, user):
            raw = super().complete(system, user)
            return raw.replace('"commands": []', f'"commands": ["{PY} -c \'print(0)\'"]')

    monkeypatch.setattr(llm, "MockProvider", ChattyMock)
    with pytest.raises(AgentError) as ei:
        run_workflow("work-issue", repo_path=repo, prompt="x", provider="mock", open_pr=True)
    assert ei.value.code == "validation"
    assert fake_gh.created == []


def test_issue_repo_mismatch_is_rejected(repo_with_remote, fake_gh, monkeypatch):
    repo, _ = repo_with_remote
    _git(repo, "remote", "set-url", "origin", "https://github.com/someone/else.git")

    from github_issue_agent.models import Issue

    def fake_get_issue(self, url):
        return Issue("acme", "widgets", 7, "t", "b", url)

    monkeypatch.setattr(FakeGitHub, "get_issue", fake_get_issue, raising=False)
    with pytest.raises(AgentError) as ei:
        run_workflow(
            "work-issue",
            repo_path=repo,
            issue_url="https://github.com/acme/widgets/issues/7",
            provider="mock",
            open_pr=False,
        )
    assert ei.value.code == "configuration"
    assert "acme/widgets" in str(ei.value)


def test_protected_branch_from_model_is_renamed(repo_with_remote, fake_gh, monkeypatch):
    repo, remote = repo_with_remote
    from github_issue_agent import llm

    class MainMock(llm.MockProvider):
        def complete(self, system, user):
            return super().complete(system, user).replace('"agent/mock-change"', '"main"')

    monkeypatch.setattr(llm, "MockProvider", MainMock)
    result = run_workflow("work-issue", repo_path=repo, prompt="x", provider="mock", open_pr=True)
    assert result.branch != "main"
    assert result.branch.startswith("agent/")
    assert _git(remote, "rev-parse", "main") == _git(repo, "rev-parse", "main")
