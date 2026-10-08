"""Thin wrappers around git for worktrees, branching, staging, committing and pushing.

Credentials are never written into ``.git/config`` or placed in argv: pushes use
a one-shot credential helper fed from an environment variable that is scoped
to the single ``git push`` process.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


class GitError(RuntimeError):
    pass


def _git(repo_path: Path, *args: str, env: dict[str, str] | None = None) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo_path,
        capture_output=True,
        text=True,
        env=env,
    )
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(_redact(a) for a in args)} failed:\n{proc.stderr.strip()}")
    return proc.stdout.strip()


_TOKEN_RE = re.compile(r"(x-access-token:)[^@]+@")


def _redact(text: str) -> str:
    return _TOKEN_RE.sub(r"\1***@", text)


def is_git_repo(repo_path: Path) -> bool:
    try:
        return _git(repo_path, "rev-parse", "--is-inside-work-tree") == "true"
    except (GitError, FileNotFoundError):
        return False


def repo_toplevel(repo_path: Path) -> Path:
    return Path(_git(repo_path, "rev-parse", "--show-toplevel"))


def current_branch(repo_path: Path) -> str:
    return _git(repo_path, "rev-parse", "--abbrev-ref", "HEAD")


def head_sha(repo_path: Path) -> str:
    return _git(repo_path, "rev-parse", "HEAD")


def has_commits(repo_path: Path) -> bool:
    try:
        _git(repo_path, "rev-parse", "--verify", "HEAD")
    except GitError:
        return False
    return True


def has_changes(repo_path: Path) -> bool:
    return bool(_git(repo_path, "status", "--porcelain"))


def remote_url(repo_path: Path, remote: str = "origin") -> str | None:
    try:
        return _git(repo_path, "remote", "get-url", remote)
    except GitError:
        return None


def branch_exists(repo_path: Path, branch: str) -> bool:
    try:
        _git(repo_path, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
        return True
    except GitError:
        pass
    try:
        _git(repo_path, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}")
        return True
    except GitError:
        return False


def valid_branch_name(repo_path: Path, branch: str) -> bool:
    if not branch or branch.startswith("-"):
        return False
    try:
        _git(repo_path, "check-ref-format", "--branch", branch)
    except GitError:
        return False
    return True


def sanitize_branch_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._/-]+", "-", name.strip())
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-/.")
    cleaned = cleaned.replace("..", "-").replace("@{", "-").replace("//", "/")
    return cleaned or "agent/change"


def pick_branch_name(
    repo_path: Path,
    requested: str,
    *,
    protected: list[str],
    base: str | None,
    run_id: str,
) -> str:
    """Return a safe, non-colliding branch name derived from ``requested``."""
    name = sanitize_branch_name(requested)
    if not name.startswith("agent/"):
        name = f"agent/{name}"
    if not valid_branch_name(repo_path, name):
        name = f"agent/change-{run_id}"
    if name in protected or name == base:
        name = f"agent/{name.split('/')[-1]}-{run_id}"
    if branch_exists(repo_path, name):
        name = f"{name}-{run_id}"
    return name


# -- worktrees ------------------------------------------------------------------
def worktree_add(repo_path: Path, target: Path, branch: str, start_point: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    _git(repo_path, "worktree", "add", "-b", branch, str(target), start_point)


def worktree_remove(repo_path: Path, target: Path, *, force: bool = True) -> None:
    args = ["worktree", "remove"]
    if force:
        args.append("--force")
    args.append(str(target))
    try:
        _git(repo_path, *args)
    except GitError:
        pass
    try:
        _git(repo_path, "worktree", "prune")
    except GitError:
        pass


def rename_current_branch(repo_path: Path, new_name: str) -> None:
    _git(repo_path, "branch", "-m", new_name)


def delete_branch(repo_path: Path, branch: str) -> None:
    try:
        _git(repo_path, "branch", "-D", branch)
    except GitError:
        pass


# -- staging / committing ---------------------------------------------------------
def stage_paths(repo_path: Path, paths: list[str]) -> None:
    """Stage exactly ``paths`` (adds, modifications and deletions)."""
    if not paths:
        return
    _git(repo_path, "add", "-A", "--", *paths)


def staged_paths(repo_path: Path) -> list[str]:
    out = _git(repo_path, "diff", "--cached", "--name-only")
    return [line for line in out.splitlines() if line]


def commit(repo_path: Path, message: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": os.environ.get("GIT_AUTHOR_NAME", "github-issue-agent"),
        "GIT_AUTHOR_EMAIL": os.environ.get("GIT_AUTHOR_EMAIL", "github-issue-agent@users.noreply.github.com"),
        "GIT_COMMITTER_NAME": os.environ.get("GIT_COMMITTER_NAME", "github-issue-agent"),
        "GIT_COMMITTER_EMAIL": os.environ.get(
            "GIT_COMMITTER_EMAIL", "github-issue-agent@users.noreply.github.com"
        ),
    }
    _git(repo_path, "commit", "-m", message, env=env)
    return head_sha(repo_path)


def commit_all(repo_path: Path, message: str) -> str:
    _git(repo_path, "add", "-A")
    return commit(repo_path, message)


def create_branch(repo_path: Path, branch: str) -> None:
    """Create and switch to a *new* branch; fails if it already exists."""
    _git(repo_path, "checkout", "-b", branch)


# -- remote ----------------------------------------------------------------------
_CRED_HELPER = '!f() { echo "username=x-access-token"; echo "password=${AGENT_GIT_PUSH_TOKEN}"; }; f'


def push(
    repo_path: Path,
    branch: str,
    remote: str = "origin",
    *,
    token: str | None = None,
    force_with_lease: bool = False,
) -> None:
    """Push ``branch`` without persisting credentials anywhere.

    When ``token`` is given a one-shot credential helper reads it from the
    push process' environment; the remote URL and ``.git/config`` are untouched
    and the token never appears in argv.
    """
    args: list[str] = []
    env = {k: v for k, v in os.environ.items()}
    env["GIT_TERMINAL_PROMPT"] = "0"
    if token:
        args += ["-c", "credential.helper=", "-c", f"credential.helper={_CRED_HELPER}"]
        env["AGENT_GIT_PUSH_TOKEN"] = token
    args += ["push", "-u"]
    if force_with_lease:
        args.append("--force-with-lease")
    args += [remote, branch]
    _git(repo_path, *args, env=env)


def remote_branch_sha(repo_path: Path, branch: str, remote: str = "origin", *, token: str | None = None) -> str | None:
    args: list[str] = []
    env = {k: v for k, v in os.environ.items()}
    env["GIT_TERMINAL_PROMPT"] = "0"
    if token:
        args += ["-c", "credential.helper=", "-c", f"credential.helper={_CRED_HELPER}"]
        env["AGENT_GIT_PUSH_TOKEN"] = token
    try:
        out = _git(repo_path, *args, "ls-remote", "--heads", remote, branch, env=env)
    except GitError:
        return None
    return out.split()[0] if out else None


def set_remote(repo_path: Path, url: str, remote: str = "origin") -> None:
    try:
        _git(repo_path, "remote", "set-url", remote, url)
    except GitError:
        _git(repo_path, "remote", "add", remote, url)
