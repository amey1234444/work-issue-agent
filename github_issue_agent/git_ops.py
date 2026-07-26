"""Thin wrappers around git for branching, committing, pushing and merging."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitError(RuntimeError):
    pass


@dataclass
class GitResult:
    exit_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


def git_raw(repo_path: Path, *args: str) -> GitResult:
    """Run git without raising, for commands whose failure is meaningful."""
    proc = subprocess.run(["git", *args], cwd=repo_path, capture_output=True, text=True)
    return GitResult(proc.returncode, proc.stdout.strip(), proc.stderr.strip())


def _git(repo_path: Path, *args: str) -> str:
    result = git_raw(repo_path, *args)
    if not result.ok:
        raise GitError(f"git {' '.join(args)} failed:\n{result.stderr}")
    return result.stdout


def current_branch(repo_path: Path) -> str:
    return _git(repo_path, "rev-parse", "--abbrev-ref", "HEAD")


def create_branch(repo_path: Path, branch: str) -> None:
    _git(repo_path, "checkout", "-B", branch)


def checkout(repo_path: Path, ref: str) -> None:
    _git(repo_path, "checkout", ref)


def has_changes(repo_path: Path) -> bool:
    return bool(_git(repo_path, "status", "--porcelain"))


def commit_all(repo_path: Path, message: str) -> None:
    _git(repo_path, "add", "-A")
    _git(repo_path, "commit", "-m", message)


def push(repo_path: Path, branch: str, remote: str = "origin", force: bool = False) -> None:
    args = ["push", "-u", remote, branch]
    if force:
        args.insert(1, "--force-with-lease")
    _git(repo_path, *args)


def set_remote(repo_path: Path, url: str, remote: str = "origin") -> None:
    if git_raw(repo_path, "remote", "get-url", remote).ok:
        _git(repo_path, "remote", "set-url", remote, url)
    else:
        _git(repo_path, "remote", "add", remote, url)


def authed_url(url: str, token: str) -> str:
    """Inject a token into an https remote URL for push access."""
    if url.startswith("https://") and "@" not in url.split("//", 1)[1].split("/", 1)[0]:
        return url.replace("https://", f"https://x-access-token:{token}@", 1)
    return url


def push_with_token(
    repo_path: Path,
    branch: str,
    token: str,
    *,
    remote: str = "origin",
    force: bool = False,
) -> None:
    """Push using a token without ever writing it into ``.git/config``.

    The credential is passed as a one-off remote URL argument, so a leaked
    repository config or a later ``git remote -v`` never exposes it.
    """
    url = remote_url(repo_path, remote)
    if not url:
        raise GitError(f"Repository has no '{remote}' remote")
    args = ["push", "--set-upstream"]
    if force:
        args.append("--force-with-lease")
    args += [authed_url(url, token), f"{branch}:{branch}"]
    result = git_raw(repo_path, *args)
    if not result.ok:
        redacted = result.stderr.replace(token, "***")
        raise GitError(f"git push failed:\n{redacted}")


def remote_url(repo_path: Path, remote: str = "origin") -> str:
    result = git_raw(repo_path, "remote", "get-url", remote)
    return result.stdout if result.ok else ""


def diff(repo_path: Path, *args: str) -> str:
    return git_raw(repo_path, "--no-pager", "diff", *args).stdout


# -- merge / conflict helpers -----------------------------------------------


def enable_rerere(repo_path: Path) -> None:
    """Let git replay conflict resolutions it has already seen in this repo."""
    git_raw(repo_path, "config", "rerere.enabled", "true")
    git_raw(repo_path, "config", "rerere.autoupdate", "true")


def use_diff3_markers(repo_path: Path) -> None:
    """Ask git for three-way markers; the base section makes merges decidable."""
    git_raw(repo_path, "config", "merge.conflictStyle", "diff3")


def fetch(repo_path: Path, remote: str = "origin", ref: str | None = None) -> GitResult:
    args = ["fetch", remote]
    if ref:
        args.append(ref)
    return git_raw(repo_path, *args)


def merge(repo_path: Path, ref: str, *, no_commit: bool = False) -> GitResult:
    """Merge ``ref`` into the current branch; a non-zero result means conflicts."""
    args = ["merge", "--no-edit"]
    if no_commit:
        args.append("--no-commit")
    args.append(ref)
    return git_raw(repo_path, *args)


def rebase(repo_path: Path, ref: str) -> GitResult:
    return git_raw(repo_path, "rebase", ref)


def conflicted_files(repo_path: Path) -> list[str]:
    """Repo-relative paths git currently reports as unmerged."""
    out = git_raw(repo_path, "diff", "--name-only", "--diff-filter=U").stdout
    return [line for line in out.splitlines() if line.strip()]


def unmerged_stages(repo_path: Path) -> dict[str, set[int]]:
    """Map path -> the index stages present (1=base, 2=ours, 3=theirs).

    A path missing stage 2 or 3 is an add/delete conflict rather than a content
    conflict, which needs a different resolution.
    """
    out = git_raw(repo_path, "ls-files", "-u").stdout
    stages: dict[str, set[int]] = {}
    for line in out.splitlines():
        if "\t" not in line:
            continue
        meta, path = line.split("\t", 1)
        parts = meta.split()
        if len(parts) >= 3:
            stages.setdefault(path.strip(), set()).add(int(parts[2]))
    return stages


def merge_in_progress(repo_path: Path) -> bool:
    git_dir = Path(_git(repo_path, "rev-parse", "--git-dir"))
    if not git_dir.is_absolute():
        git_dir = repo_path / git_dir
    return any(
        (git_dir / marker).exists()
        for marker in ("MERGE_HEAD", "REBASE_HEAD", "CHERRY_PICK_HEAD", "rebase-merge", "rebase-apply")
    )


def rebase_in_progress(repo_path: Path) -> bool:
    git_dir = Path(_git(repo_path, "rev-parse", "--git-dir"))
    if not git_dir.is_absolute():
        git_dir = repo_path / git_dir
    return (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists()


def abort_merge(repo_path: Path) -> None:
    if rebase_in_progress(repo_path):
        git_raw(repo_path, "rebase", "--abort")
    else:
        git_raw(repo_path, "merge", "--abort")


def stage(repo_path: Path, paths: list[str]) -> None:
    if paths:
        _git(repo_path, "add", "--", *paths)


def continue_merge(repo_path: Path, message: str | None = None) -> GitResult:
    """Finish the in-progress merge or rebase after conflicts were resolved."""
    if rebase_in_progress(repo_path):
        return git_raw(repo_path, "-c", "core.editor=true", "rebase", "--continue")
    args = ["commit", "--no-edit"]
    if message:
        args = ["commit", "-m", message]
    return git_raw(repo_path, *args)


def show_file(repo_path: Path, ref: str, path: str) -> str:
    result = git_raw(repo_path, "show", f"{ref}:{path}")
    return result.stdout if result.ok else ""


def merge_base(repo_path: Path, a: str, b: str) -> str:
    result = git_raw(repo_path, "merge-base", a, b)
    return result.stdout if result.ok else ""


def would_conflict(repo_path: Path, base_ref: str) -> bool:
    """Predict conflicts against ``base_ref`` without touching the working tree."""
    head = git_raw(repo_path, "rev-parse", "HEAD").stdout
    base = merge_base(repo_path, "HEAD", base_ref)
    if not head or not base:
        return False
    result = git_raw(repo_path, "merge-tree", base, head, base_ref)
    return "<<<<<<<" in result.stdout
