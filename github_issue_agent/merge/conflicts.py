"""Parsing and rewriting git conflict markers.

A conflicted file is treated as a sequence of clean segments and
:class:`ConflictBlock` regions, so a resolution can be applied to one hunk
without touching the rest of the file.

Both the two-way form::

    <<<<<<< HEAD
    ours
    =======
    theirs
    >>>>>>> branch

and the three-way ``diff3`` form (with a ``||||||| base`` section) are
supported.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

OURS_MARKER = "<<<<<<<"
BASE_MARKER = "|||||||"
SPLIT_MARKER = "======="
THEIRS_MARKER = ">>>>>>>"

_MARKER_RE = re.compile(rf"^({re.escape(OURS_MARKER)}|{re.escape(THEIRS_MARKER)})", re.MULTILINE)


class ConflictParseError(RuntimeError):
    pass


@dataclass
class ConflictBlock:
    """One ``<<<<<<< ... >>>>>>>`` region."""

    ours: list[str] = field(default_factory=list)
    theirs: list[str] = field(default_factory=list)
    base: list[str] | None = None
    ours_label: str = "HEAD"
    theirs_label: str = "incoming"
    start_line: int = 0

    def render(self) -> str:
        """Re-emit the block with its markers (used to locate it in a file)."""
        parts = [f"{OURS_MARKER} {self.ours_label}".rstrip(), *self.ours]
        if self.base is not None:
            parts += [f"{BASE_MARKER} base", *self.base]
        parts += [SPLIT_MARKER, *self.theirs, f"{THEIRS_MARKER} {self.theirs_label}".rstrip()]
        return "\n".join(parts)

    def as_prompt(self, path: str, index: int) -> str:
        base = "\n".join(self.base) if self.base is not None else "(not available)"
        return (
            f'<conflict path="{path}" index="{index}" line="{self.start_line}">\n'
            f"<ours label=\"{self.ours_label}\">\n" + "\n".join(self.ours) + "\n</ours>\n"
            f"<base>\n{base}\n</base>\n"
            f"<theirs label=\"{self.theirs_label}\">\n" + "\n".join(self.theirs) + "\n</theirs>\n"
            "</conflict>"
        )


@dataclass
class ConflictedFile:
    """A file split into literal segments and conflict blocks."""

    path: str
    #: Alternating content: ``str`` segments and :class:`ConflictBlock` regions.
    parts: list[str | ConflictBlock] = field(default_factory=list)
    trailing_newline: bool = True

    @property
    def blocks(self) -> list[ConflictBlock]:
        return [p for p in self.parts if isinstance(p, ConflictBlock)]

    def render(self, resolutions: dict[int, list[str]] | None = None) -> str:
        """Rebuild the file; ``resolutions`` maps block index -> replacement lines."""
        resolutions = resolutions or {}
        lines: list[str] = []
        block_index = 0
        for part in self.parts:
            if isinstance(part, str):
                if part:
                    lines.extend(part.split("\n"))
            else:
                if block_index in resolutions:
                    lines.extend(resolutions[block_index])
                else:
                    lines.extend(part.render().split("\n"))
                block_index += 1
        text = "\n".join(lines)
        if self.trailing_newline and not text.endswith("\n"):
            text += "\n"
        return text


def has_conflict_markers(text: str) -> bool:
    return bool(_MARKER_RE.search(text))


def parse_conflicts(text: str, path: str = "") -> ConflictedFile:
    """Split conflicted file content into segments and blocks."""
    trailing_newline = text.endswith("\n")
    lines = text.split("\n")
    if trailing_newline:
        lines = lines[:-1]

    parsed = ConflictedFile(path=path, trailing_newline=trailing_newline)
    buffer: list[str] = []
    index = 0

    while index < len(lines):
        line = lines[index]
        if not line.startswith(OURS_MARKER):
            buffer.append(line)
            index += 1
            continue

        parsed.parts.append("\n".join(buffer))
        buffer = []
        block = ConflictBlock(
            ours_label=line[len(OURS_MARKER) :].strip() or "HEAD",
            start_line=index + 1,
        )
        index += 1
        section = "ours"
        closed = False
        while index < len(lines):
            current = lines[index]
            if current.startswith(BASE_MARKER):
                block.base = []
                section = "base"
            elif current.startswith(SPLIT_MARKER):
                section = "theirs"
            elif current.startswith(THEIRS_MARKER):
                block.theirs_label = current[len(THEIRS_MARKER) :].strip() or "incoming"
                closed = True
                index += 1
                break
            elif section == "ours":
                block.ours.append(current)
            elif section == "base" and block.base is not None:
                block.base.append(current)
            else:
                block.theirs.append(current)
            index += 1
        if not closed:
            raise ConflictParseError(
                f"Unterminated conflict block starting at line {block.start_line}"
                + (f" in {path}" if path else "")
            )
        parsed.parts.append(block)

    parsed.parts.append("\n".join(buffer))
    return parsed


def read_conflicted_file(repo_path: Path, rel: str) -> ConflictedFile:
    text = (repo_path / rel).read_text(encoding="utf-8", errors="replace")
    return parse_conflicts(text, rel)


def write_resolved_file(repo_path: Path, parsed: ConflictedFile, resolutions: dict[int, list[str]]) -> str:
    content = parsed.render(resolutions)
    (repo_path / parsed.path).write_text(content, encoding="utf-8")
    return content
