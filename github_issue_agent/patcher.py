"""A parser and applier for the ``apply_patch`` (V4A) envelope format.

Models are far more reliable emitting small context diffs than whole files, and
a diff makes accidental deletion of unrelated code visible instead of silent.

Format::

    *** Begin Patch
    *** Update File: src/app.py
    @@
     def handler():
    -    return None
    +    return compute()
    *** Add File: docs/new.md
    +# Title
    *** Delete File: old.py
    *** End Patch

Hunks are located by their context lines, so line numbers are never required.
Matching is exact first, then whitespace-insensitive; anything ambiguous fails
loudly with an actionable message rather than guessing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_BEGIN = "*** Begin Patch"
_END = "*** End Patch"
_ADD = "*** Add File: "
_UPDATE = "*** Update File: "
_DELETE = "*** Delete File: "
_MOVE = "*** Move to: "


class PatchError(RuntimeError):
    """Raised when a patch cannot be parsed or applied cleanly."""


@dataclass
class Hunk:
    """One ``@@`` block: context lines plus the +/- edits inside it."""

    old_lines: list[str] = field(default_factory=list)
    new_lines: list[str] = field(default_factory=list)


@dataclass
class FileOperation:
    action: str  # "add" | "update" | "delete"
    path: str
    move_to: str | None = None
    new_content: str = ""
    hunks: list[Hunk] = field(default_factory=list)


def _strip_marker(line: str, marker: str) -> str:
    return line[len(marker) :].strip()


def parse_patch(text: str) -> list[FileOperation]:
    """Parse a patch envelope into per-file operations."""
    lines = text.replace("\r\n", "\n").split("\n")
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == _BEGIN)
    except StopIteration as exc:
        raise PatchError(f"Patch must start with '{_BEGIN}'") from exc
    try:
        stop = next(i for i in range(len(lines) - 1, start, -1) if lines[i].strip() == _END)
    except StopIteration as exc:
        raise PatchError(f"Patch must end with '{_END}'") from exc

    operations: list[FileOperation] = []
    current: FileOperation | None = None
    hunk: Hunk | None = None

    def close_hunk() -> None:
        nonlocal hunk
        if current is not None and hunk is not None:
            current.hunks.append(hunk)
        hunk = None

    for raw in lines[start + 1 : stop]:
        if raw.startswith(_ADD):
            close_hunk()
            current = FileOperation(action="add", path=_strip_marker(raw, _ADD))
            operations.append(current)
        elif raw.startswith(_UPDATE):
            close_hunk()
            current = FileOperation(action="update", path=_strip_marker(raw, _UPDATE))
            operations.append(current)
        elif raw.startswith(_DELETE):
            close_hunk()
            current = FileOperation(action="delete", path=_strip_marker(raw, _DELETE))
            operations.append(current)
        elif raw.startswith(_MOVE):
            if current is None:
                raise PatchError("'*** Move to:' must follow a file section")
            current.move_to = _strip_marker(raw, _MOVE)
        elif current is None:
            if raw.strip():
                raise PatchError(f"Unexpected line before any file section: {raw!r}")
        elif current.action == "add":
            if raw.startswith("+"):
                current.new_content += raw[1:] + "\n"
            elif raw.strip():
                raise PatchError(
                    f"Lines in an '*** Add File' section must start with '+': {raw!r}"
                )
        elif current.action == "update":
            if raw.startswith("@@"):
                close_hunk()
                hunk = Hunk()
            else:
                if hunk is None:
                    hunk = Hunk()
                if raw.startswith("+"):
                    hunk.new_lines.append(raw[1:])
                elif raw.startswith("-"):
                    hunk.old_lines.append(raw[1:])
                else:
                    body = raw[1:] if raw.startswith(" ") else raw
                    hunk.old_lines.append(body)
                    hunk.new_lines.append(body)

    close_hunk()
    if not operations:
        raise PatchError("Patch contains no file operations")
    for op in operations:
        if not op.path:
            raise PatchError("A file section is missing its path")
        if op.action == "update" and not op.hunks:
            raise PatchError(f"'*** Update File: {op.path}' contains no @@ hunks")
    return operations


def _normalise(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def _find_hunk(haystack: list[str], needle: list[str], path: str) -> int:
    if not needle:
        raise PatchError(f"Empty hunk for {path}")
    span = len(needle)
    exact = [i for i in range(len(haystack) - span + 1) if haystack[i : i + span] == needle]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise PatchError(
            f"Hunk context is ambiguous in {path} ({len(exact)} matches). "
            "Include more surrounding context lines."
        )

    loose_needle = [_normalise(line) for line in needle]
    loose = [
        i
        for i in range(len(haystack) - span + 1)
        if [_normalise(line) for line in haystack[i : i + span]] == loose_needle
    ]
    if len(loose) == 1:
        return loose[0]
    if len(loose) > 1:
        raise PatchError(
            f"Hunk context is ambiguous in {path} ({len(loose)} whitespace-insensitive matches). "
            "Include more surrounding context lines."
        )
    preview = "\n".join(needle[:6])
    raise PatchError(
        f"Hunk context not found in {path}. Re-read the file and rebuild the patch.\n"
        f"Context searched for:\n{preview}"
    )


def apply_operation(repo_path: Path, op: FileOperation) -> str:
    """Apply one file operation and return a human-readable description."""
    root = repo_path.resolve()
    target = (root / op.path).resolve()
    if target != root and root not in target.parents:
        raise PatchError(f"Refusing to touch path outside the repository: {op.path!r}")

    if op.action == "delete":
        if not target.exists():
            raise PatchError(f"Cannot delete missing file: {op.path}")
        target.unlink()
        return f"deleted {op.path}"

    if op.action == "add":
        if target.exists():
            raise PatchError(
                f"{op.path} already exists; use '*** Update File' instead of '*** Add File'"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(op.new_content, encoding="utf-8")
        return f"created {op.path}"

    if not target.is_file():
        raise PatchError(f"Cannot update missing file: {op.path}")
    original = target.read_text(encoding="utf-8")
    lines = original.split("\n")
    trailing_newline = original.endswith("\n")
    if trailing_newline:
        lines = lines[:-1]

    for hunk in op.hunks:
        index = _find_hunk(lines, hunk.old_lines, op.path)
        lines[index : index + len(hunk.old_lines)] = hunk.new_lines

    updated = "\n".join(lines) + ("\n" if trailing_newline or lines else "")
    destination = target
    described = f"modified {op.path}"
    if op.move_to:
        destination = (root / op.move_to).resolve()
        if destination != root and root not in destination.parents:
            raise PatchError(f"Refusing to move outside the repository: {op.move_to!r}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        target.unlink()
        described = f"moved {op.path} -> {op.move_to}"
    destination.write_text(updated, encoding="utf-8")
    return described


def apply_patch(repo_path: Path, text: str) -> list[str]:
    """Parse and apply a whole patch envelope atomically.

    If any operation fails, every file touched by this call is restored, so the
    model never has to reason about a half-applied patch.
    """
    operations = parse_patch(text)
    backups: dict[Path, str | None] = {}
    results: list[str] = []

    def snapshot(path: str) -> None:
        full = (repo_path / path).resolve()
        if full not in backups:
            backups[full] = full.read_text(encoding="utf-8") if full.is_file() else None

    try:
        for op in operations:
            snapshot(op.path)
            if op.move_to:
                snapshot(op.move_to)
            results.append(apply_operation(repo_path, op))
    except Exception:
        for full, content in backups.items():
            if content is None:
                if full.exists():
                    full.unlink()
            else:
                full.parent.mkdir(parents=True, exist_ok=True)
                full.write_text(content, encoding="utf-8")
        raise
    return results
