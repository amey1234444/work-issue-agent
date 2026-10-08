"""Apply LLM-produced file edits as one transaction inside the workspace.

All paths are validated by the shared :class:`~.paths.PathPolicy` *before* any
file is read or written. Existing files are snapshotted byte-for-byte together
with their mode; if any operation fails, every earlier operation is rolled back
so the workspace is never left half-edited.

Semantics are strict: ``create`` requires the target to be absent, ``modify``
and ``delete`` require it to exist.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from .models import FileEdit
from .paths import PathPolicy, PathPolicyError


class EditError(RuntimeError):
    pass


@dataclass(frozen=True)
class FileChange:
    """One applied change, with hashes so consumers can verify what happened."""

    path: str
    action: str  # created | modified | deleted
    old_hash: str | None
    new_hash: str | None

    def describe(self) -> str:
        return f"{self.action} {self.path}"


@dataclass
class _Snapshot:
    target: Path
    existed: bool
    data: bytes = b""
    mode: int = 0
    created_dirs: list[Path] | None = None


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    return sha256_bytes(path.read_bytes())


def _snapshot(target: Path) -> _Snapshot:
    if target.exists():
        if target.is_dir():
            raise EditError(f"Refusing to edit a directory: {target}")
        return _Snapshot(target, True, target.read_bytes(), target.stat().st_mode)
    return _Snapshot(target, False)


def _restore(snap: _Snapshot) -> None:
    if snap.existed:
        snap.target.parent.mkdir(parents=True, exist_ok=True)
        snap.target.write_bytes(snap.data)
        os.chmod(snap.target, snap.mode & 0o7777)
        return
    if snap.target.exists():
        snap.target.unlink()
    for d in reversed(snap.created_dirs or []):
        try:
            d.rmdir()
        except OSError:
            break


def _mkdirs(target: Path, root: Path) -> list[Path]:
    """Create missing parents of ``target`` and return them, deepest last."""
    created: list[Path] = []
    missing: list[Path] = []
    parent = target.parent
    while not parent.exists() and parent != root:
        missing.append(parent)
        parent = parent.parent
    for d in reversed(missing):
        d.mkdir()
        created.append(d)
    return created


def apply_edits(
    repo_path: Path,
    edits: list[FileEdit],
    *,
    policy: PathPolicy | None = None,
) -> list[FileChange]:
    """Validate, then apply all ``edits`` atomically; return what changed.

    Raises :class:`EditError` (after rolling everything back) if any edit is
    invalid or fails to apply.
    """
    policy = policy or PathPolicy(repo_path)
    root = policy.root

    # Phase 1: validate every path and precondition before touching anything.
    resolved: list[tuple[FileEdit, Path]] = []
    seen: set[Path] = set()
    for edit in edits:
        if edit.action not in ("create", "modify", "delete"):
            raise EditError(f"Unknown edit action: {edit.action!r} for {edit.path!r}")
        try:
            target = policy.resolve(edit.path)
        except PathPolicyError as exc:
            raise EditError(str(exc)) from exc
        if target == root:
            raise EditError("Refusing to edit the workspace root.")
        if target in seen:
            raise EditError(f"Path edited twice in one transaction: {edit.path!r}")
        seen.add(target)
        if edit.action == "create" and target.exists():
            raise EditError(f"create: {edit.path!r} already exists (use modify).")
        if edit.action in ("modify", "delete") and not target.is_file():
            raise EditError(f"{edit.action}: {edit.path!r} does not exist.")
        resolved.append((edit, target))

    # Phase 2: apply with snapshots; roll back on any failure.
    snapshots: list[_Snapshot] = []
    changes: list[FileChange] = []
    try:
        for edit, target in resolved:
            snap = _snapshot(target)
            snapshots.append(snap)
            if edit.action == "delete":
                old_hash = sha256_bytes(snap.data)
                target.unlink()
                changes.append(FileChange(edit.path, "deleted", old_hash, None))
                continue
            snap.created_dirs = _mkdirs(target, root)
            data = edit.content.encode("utf-8")
            tmp = target.with_name(target.name + ".agent-tmp")
            tmp.write_bytes(data)
            if snap.existed:
                os.chmod(tmp, snap.mode & 0o7777)
            os.replace(tmp, target)
            changes.append(
                FileChange(
                    edit.path,
                    "modified" if snap.existed else "created",
                    sha256_bytes(snap.data) if snap.existed else None,
                    sha256_bytes(data),
                )
            )
    except Exception as exc:
        for snap in reversed(snapshots):
            _restore(snap)
        raise EditError(f"Edit transaction failed and was rolled back: {exc}") from exc
    return changes


def merge_changes(previous: list[FileChange], latest: list[FileChange]) -> list[FileChange]:
    """Combine change lists across attempts so nothing on disk goes unreported."""
    by_path: dict[str, FileChange] = {c.path: c for c in previous}
    for change in latest:
        prior = by_path.get(change.path)
        if prior is None:
            by_path[change.path] = change
            continue
        if prior.action == "created" and change.action == "deleted":
            del by_path[change.path]
            continue
        action = "created" if prior.action == "created" else change.action
        if prior.action == "deleted" and change.action == "created":
            action = "modified"
        by_path[change.path] = FileChange(change.path, action, prior.old_hash, change.new_hash)
    return list(by_path.values())


def hash_paths(root: Path, rel_paths: list[str]) -> str:
    """Stable hash of the given files' current contents (absent files count too)."""
    h = hashlib.sha256()
    for rel in sorted(set(rel_paths)):
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        fp = root / rel
        digest = _hash_file(fp)
        h.update(digest.encode("utf-8") if digest is not None else b"<absent>")
        h.update(b"\n")
    return h.hexdigest()
