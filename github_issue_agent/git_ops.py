"""Thin wrappers around git for branching, committing and pushing."""

from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    pass


def _git(repo_path: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed:\n{proc.stderr.strip()}")
    return proc.stdout.strip()


def current_branch(repo_path: Path) -> str:
    return _git(repo_path, "rev-parse", "--abbrev-ref", "HEAD")


def create_branch(repo_path: Path, branch: str) -> None:
    _git(repo_path, "checkout", "-B", branch)


def has_changes(repo_path: Path) -> bool:
    return bool(_git(repo_path, "status", "--porcelain"))


def commit_all(repo_path: Path, message: str) -> None:
    _git(repo_path, "add", "-A")
    _git(repo_path, "commit", "-m", message)


def push(repo_path: Path, branch: str, remote: str = "origin") -> None:
    _git(repo_path, "push", "-u", remote, branch)


def set_remote(repo_path: Path, url: str, remote: str = "origin") -> None:
    try:
        _git(repo_path, "remote", "set-url", remote, url)
    except GitError:
        _git(repo_path, "remote", "add", remote, url)
