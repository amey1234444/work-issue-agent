"""Apply LLM-produced file edits safely within the target repository."""

from __future__ import annotations

from pathlib import Path

from .models import FileEdit


class EditError(RuntimeError):
    pass


def _resolve_within(repo_path: Path, rel: str) -> Path:
    """Resolve ``rel`` against repo root and refuse paths that escape it."""
    root = repo_path.resolve()
    target = (root / rel).resolve()
    if target != root and root not in target.parents:
        raise EditError(f"Refusing to edit path outside the repo: {rel!r}")
    return target


def apply_edits(repo_path: Path, edits: list[FileEdit]) -> list[str]:
    """Apply edits and return a human-readable list of what changed."""
    changed: list[str] = []
    for edit in edits:
        target = _resolve_within(repo_path, edit.path)
        if edit.action == "delete":
            if target.exists():
                target.unlink()
                changed.append(f"deleted {edit.path}")
            continue
        if edit.action in ("create", "modify"):
            target.parent.mkdir(parents=True, exist_ok=True)
            existed = target.exists()
            target.write_text(edit.content, encoding="utf-8")
            changed.append(f"{'modified' if existed else 'created'} {edit.path}")
        else:  # pragma: no cover - guarded by dataclass typing
            raise EditError(f"Unknown edit action: {edit.action!r}")
    return changed
