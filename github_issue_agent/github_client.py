"""Minimal GitHub REST client: parse issue URLs, fetch issues and open PRs.

Requests to GitHub are retried on transient failures, and PR creation is
idempotent: an existing open PR for the same head/base is returned instead of
failing with 422, so a run that timed out after pushing can be reconciled.
"""

from __future__ import annotations

import re
import time
from collections.abc import Mapping

import requests

from .models import Issue

_API = "https://api.github.com"
_ISSUE_URL_RE = re.compile(r"github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/issues/(?P<number>\d+)")
_REPO_URL_RE = re.compile(r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$")
_RETRY_STATUSES = {500, 502, 503, 504}


class GitHubError(RuntimeError):
    pass


class GitHubClient:
    def __init__(self, token: str | None, *, retries: int = 3, backoff: float = 1.0):
        if not token:
            raise GitHubError(
                "A GitHub token is required (set GITHUB_TOKEN or GITHUB_PAT). "
                "Use a classic token with the 'repo' scope."
            )
        self._retries = retries
        self._backoff = backoff
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    # -- transport -----------------------------------------------------------
    def _request(
        self,
        method: str,
        url: str,
        *,
        json: Mapping[str, object] | None = None,
        params: Mapping[str, str | int] | None = None,
    ) -> requests.Response:
        attempt = 0
        while True:
            attempt += 1
            try:
                resp = self._session.request(method, url, json=json, params=params, timeout=60)
            except requests.RequestException as exc:
                if attempt > self._retries:
                    raise GitHubError(f"GitHub request failed: {exc}") from exc
                time.sleep(self._backoff * attempt)
                continue
            if resp.status_code in _RETRY_STATUSES and attempt <= self._retries:
                time.sleep(self._backoff * attempt)
                continue
            if resp.status_code in (403, 429) and resp.headers.get("X-RateLimit-Remaining") == "0":
                reset = resp.headers.get("X-RateLimit-Reset", "")
                raise GitHubError(f"GitHub rate limit exceeded (resets at epoch {reset}).")
            return resp

    # -- issue helpers -------------------------------------------------------
    @staticmethod
    def parse_issue_url(url: str) -> tuple[str, str, int]:
        m = _ISSUE_URL_RE.search(url)
        if not m:
            raise GitHubError(f"Not a valid GitHub issue URL: {url!r}")
        return m["owner"], m["repo"], int(m["number"])

    @staticmethod
    def parse_repo_url(url: str) -> tuple[str, str]:
        m = _REPO_URL_RE.search(url.strip())
        if not m:
            raise GitHubError(f"Not a valid GitHub repo URL: {url!r}")
        return m["owner"], m["repo"]

    def get_issue(self, url: str) -> Issue:
        owner, repo, number = self.parse_issue_url(url)
        resp = self._request("GET", f"{_API}/repos/{owner}/{repo}/issues/{number}")
        if resp.status_code != 200:
            raise GitHubError(f"Failed to fetch issue ({resp.status_code}): {resp.text}")
        data = resp.json()
        if "pull_request" in data:
            raise GitHubError(f"{url} is a pull request, not an issue.")
        return Issue(
            owner=owner,
            repo=repo,
            number=number,
            title=data.get("title", ""),
            body=data.get("body") or "",
            url=data.get("html_url", url),
            labels=[lbl["name"] for lbl in data.get("labels", []) if isinstance(lbl, dict)],
        )

    def get_issue_comments(self, owner: str, repo: str, number: int, *, limit: int = 50) -> list[str]:
        comments: list[str] = []
        page = 1
        while len(comments) < limit:
            resp = self._request(
                "GET",
                f"{_API}/repos/{owner}/{repo}/issues/{number}/comments",
                params={"per_page": 100, "page": page},
            )
            if resp.status_code != 200:
                break
            batch = resp.json()
            if not batch:
                break
            comments.extend(c.get("body") or "" for c in batch if isinstance(c, dict))
            if len(batch) < 100:
                break
            page += 1
        return comments[:limit]

    # -- repo / PR helpers ---------------------------------------------------
    def default_branch(self, owner: str, repo: str) -> str:
        resp = self._request("GET", f"{_API}/repos/{owner}/{repo}")
        if resp.status_code != 200:
            raise GitHubError(f"Failed to read repo ({resp.status_code}): {resp.text}")
        return resp.json().get("default_branch", "main")

    def create_repo(self, name: str, private: bool = False, description: str = "") -> dict:
        resp = self._request(
            "POST",
            f"{_API}/user/repos",
            json={"name": name, "private": private, "description": description, "auto_init": True},
        )
        if resp.status_code not in (201, 202):
            raise GitHubError(f"Failed to create repo ({resp.status_code}): {resp.text}")
        return resp.json()

    def find_pull_request(self, owner: str, repo: str, head: str, base: str) -> str | None:
        resp = self._request(
            "GET",
            f"{_API}/repos/{owner}/{repo}/pulls",
            params={"head": f"{owner}:{head}", "base": base, "state": "open"},
        )
        if resp.status_code != 200:
            return None
        for pr in resp.json():
            if isinstance(pr, dict) and pr.get("html_url"):
                return str(pr["html_url"])
        return None

    def create_pull_request(
        self,
        owner: str,
        repo: str,
        title: str,
        head: str,
        base: str,
        body: str,
        *,
        draft: bool = False,
    ) -> str:
        existing = self.find_pull_request(owner, repo, head, base)
        if existing:
            return existing
        resp = self._request(
            "POST",
            f"{_API}/repos/{owner}/{repo}/pulls",
            json={"title": title, "head": head, "base": base, "body": body, "draft": draft},
        )
        if resp.status_code == 422:
            existing = self.find_pull_request(owner, repo, head, base)
            if existing:
                return existing
        if resp.status_code != 201:
            raise GitHubError(f"Failed to open PR ({resp.status_code}): {resp.text}")
        return resp.json().get("html_url", "")
