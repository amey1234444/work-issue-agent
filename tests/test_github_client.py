from __future__ import annotations

import pytest
import requests

from github_issue_agent.github_client import GitHubClient, GitHubError


class FakeResponse:
    def __init__(self, status: int, payload=None, headers=None):
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}
        self.text = str(payload)

    def json(self):
        return self._payload


class ScriptedSession:
    """Replays a scripted list of responses/exceptions and records calls."""

    def __init__(self, script):
        self.script = list(script)
        self.calls: list[tuple[str, str, dict]] = []
        self.headers: dict[str, str] = {}

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make_client(script) -> tuple[GitHubClient, ScriptedSession]:
    client = GitHubClient("tok", retries=2, backoff=0)
    session = ScriptedSession(script)
    client._session = session  # type: ignore[assignment]
    return client, session


def test_parse_urls():
    assert GitHubClient.parse_issue_url("https://github.com/o/r/issues/12") == ("o", "r", 12)
    assert GitHubClient.parse_repo_url("git@github.com:o/r.git") == ("o", "r")
    assert GitHubClient.parse_repo_url("https://github.com/o/r") == ("o", "r")
    assert GitHubClient.parse_repo_url("https://github.com/o/r.git\n") == ("o", "r")
    with pytest.raises(GitHubError):
        GitHubClient.parse_repo_url("/tmp/local.git")
    with pytest.raises(GitHubError):
        GitHubClient.parse_issue_url("https://github.com/o/r/pull/3")


def test_token_required():
    with pytest.raises(GitHubError):
        GitHubClient(None)


def test_token_only_in_header_and_requests_have_timeout():
    client, session = make_client([FakeResponse(200, {"default_branch": "dev"})])
    assert client.default_branch("o", "r") == "dev"
    assert session.calls[0][2]["timeout"] == 60
    assert "tok" not in session.calls[0][1]


def test_transient_errors_are_retried():
    client, session = make_client(
        [requests.ConnectionError("boom"), FakeResponse(503), FakeResponse(200, {"default_branch": "main"})]
    )
    assert client.default_branch("o", "r") == "main"
    assert len(session.calls) == 3


def test_retries_are_bounded():
    client, _ = make_client([FakeResponse(502), FakeResponse(502), FakeResponse(502)])
    with pytest.raises(GitHubError):
        client.default_branch("o", "r")


def test_rate_limit_is_reported():
    client, _ = make_client([FakeResponse(403, {}, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1"})])
    with pytest.raises(GitHubError, match="rate limit"):
        client.default_branch("o", "r")


def test_get_issue_rejects_pull_requests():
    client, _ = make_client([FakeResponse(200, {"title": "t", "pull_request": {}})])
    with pytest.raises(GitHubError, match="pull request"):
        client.get_issue("https://github.com/o/r/issues/1")


def test_create_pr_reuses_existing_open_pr():
    client, session = make_client([FakeResponse(200, [{"html_url": "https://github.com/o/r/pull/9"}])])
    assert client.create_pull_request("o", "r", "t", "b", "main", "body") == "https://github.com/o/r/pull/9"
    assert [m for m, _, _ in session.calls] == ["GET"]


def test_create_pr_reconciles_after_422():
    client, session = make_client(
        [
            FakeResponse(200, []),  # lookup before create: nothing yet
            FakeResponse(422, {"message": "A pull request already exists"}),
            FakeResponse(200, [{"html_url": "https://github.com/o/r/pull/10"}]),
        ]
    )
    assert client.create_pull_request("o", "r", "t", "b", "main", "body", draft=True) == "https://github.com/o/r/pull/10"
    assert session.calls[1][2]["json"]["draft"] is True


def test_create_pr_failure_is_raised():
    client, _ = make_client([FakeResponse(200, []), FakeResponse(404, {"message": "nope"})])
    with pytest.raises(GitHubError, match="404"):
        client.create_pull_request("o", "r", "t", "b", "main", "body")
