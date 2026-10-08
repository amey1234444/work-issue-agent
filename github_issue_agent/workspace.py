"""Disposable, isolated workspaces for agent runs.

The agent never edits the developer's checkout directly. For git repositories a
``git worktree`` is created under ``<repo>/.agent_work/<run_id>`` on a private
branch starting at the current ``HEAD``; the developer's branch, index and
uncommitted files are left untouched. Non-git directories fall back to
in-place editing (transactional editor still guarantees rollback).
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from . import git_ops
from .errors import AgentError


@dataclass
class Workspace:
    """Where the run edits, validates and commits."""

    origin: Path
    """The developer's checkout (never mutated except for ref creation)."""
    path: Path
    """Directory the agent works in (a worktree, or ``origin`` when isolated=False)."""
    branch: str | None
    isolated: bool
    base_ref: str | None
    run_id: str

    def cleanup(self, *, keep_branch: bool) -> None:
        if not self.isolated:
            return
        git_ops.worktree_remove(self.origin, self.path)
        if self.path.exists():
            shutil.rmtree(self.path, ignore_errors=True)
        if not keep_branch and self.branch:
            git_ops.delete_branch(self.origin, self.branch)


def create_workspace(repo_path: Path, run_id: str, *, isolate: bool = True) -> Workspace:
    repo_path = repo_path.resolve()
    if not isolate or not git_ops.is_git_repo(repo_path) or not git_ops.has_commits(repo_path):
        return Workspace(repo_path, repo_path, None, False, None, run_id)

    top = git_ops.repo_toplevel(repo_path)
    base_ref = git_ops.head_sha(top)
    branch = f"agent/run-{run_id}"
    target = top / ".agent_work" / run_id
    if target.exists():
        raise AgentError(
            f"Workspace directory already exists: {target}",
            code="workspace",
            phase="workspace",
            recovery="Remove the stale directory or use a different run id.",
        )
    try:
        git_ops.worktree_add(top, target, branch, base_ref)
    except git_ops.GitError as exc:
        raise AgentError(
            f"Could not create isolated worktree: {exc}",
            code="workspace",
            phase="workspace",
            recovery="Ensure git >= 2.5 is installed and the repository is not locked.",
        ) from exc
    _ensure_excluded(top)
    return Workspace(top, target, branch, True, base_ref, run_id)


def _ensure_excluded(top: Path) -> None:
    """Make sure ``.agent_work/`` never shows up as untracked in the developer's repo."""
    exclude = top / ".git" / "info" / "exclude"
    try:
        exclude.parent.mkdir(parents=True, exist_ok=True)
        existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        if ".agent_work/" not in existing:
            with exclude.open("a", encoding="utf-8") as fh:
                if existing and not existing.endswith("\n"):
                    fh.write("\n")
                fh.write(".agent_work/\n")
    except OSError:
        pass
