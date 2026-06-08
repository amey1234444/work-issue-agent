"""Minimal GitHub REST client: parse issue URLs, fetch issues and open PRs."""

from __future__ import annotations

import re

import requests

from .models import Issue

_API = "https://api.github.com"
_ISSUE_URL_RE = re.compile(r"github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/issues/(?P<number>\d+)")
_REPO_URL_RE = re.compile(r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/.]+)")


class GitHubError(RuntimeError):
    pass


class GitHubClient:
    def __init__(self, token: str | None):
        if not token:
            raise GitHubError(
                "A GitHub token is required (set GITHUB_TOKEN or GITHUB_PAT). "
                "Use a classic token with the 'repo' scope."
            )
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    # -- issue helpers -------------------------------------------------------
    @staticmethod
    def parse_issue_url(url: str) -> tuple[str, str, int]:
        m = _ISSUE_URL_RE.search(url)
        if not m:
            raise GitHubError(f"Not a valid GitHub issue URL: {url!r}")
        return m["owner"], m["repo"], int(m["number"])

    @staticmethod
    def parse_repo_url(url: str) -> tuple[str, str]:
        m = _REPO_URL_RE.search(url)
        if not m:
            raise GitHubError(f"Not a valid GitHub repo URL: {url!r}")
        return m["owner"], m["repo"]

    def get_issue(self, url: str) -> Issue:
        owner, repo, number = self.parse_issue_url(url)
        resp = self._session.get(f"{_API}/repos/{owner}/{repo}/issues/{number}")
        if resp.status_code != 200:
            raise GitHubError(f"Failed to fetch issue ({resp.status_code}): {resp.text}")
        data = resp.json()
        return Issue(
            owner=owner,
            repo=repo,
            number=number,
            title=data.get("title", ""),
            body=data.get("body") or "",
            url=data.get("html_url", url),
            labels=[lbl["name"] for lbl in data.get("labels", []) if isinstance(lbl, dict)],
        )

    # -- repo / PR helpers ---------------------------------------------------
    def default_branch(self, owner: str, repo: str) -> str:
        resp = self._session.get(f"{_API}/repos/{owner}/{repo}")
        if resp.status_code != 200:
            raise GitHubError(f"Failed to read repo ({resp.status_code}): {resp.text}")
        return resp.json().get("default_branch", "main")

    def create_repo(self, name: str, private: bool = False, description: str = "") -> dict:
        resp = self._session.post(
            f"{_API}/user/repos",
            json={"name": name, "private": private, "description": description, "auto_init": True},
        )
        if resp.status_code not in (201, 202):
            raise GitHubError(f"Failed to create repo ({resp.status_code}): {resp.text}")
        return resp.json()

    def create_pull_request(
        self,
        owner: str,
        repo: str,
        title: str,
        head: str,
        base: str,
        body: str,
    ) -> str:
        resp = self._session.post(
            f"{_API}/repos/{owner}/{repo}/pulls",
            json={"title": title, "head": head, "base": base, "body": body},
        )
        if resp.status_code != 201:
            raise GitHubError(f"Failed to open PR ({resp.status_code}): {resp.text}")
        return resp.json().get("html_url", "")
