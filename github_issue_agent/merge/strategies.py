"""Deterministic conflict-resolution strategies.

Most real merge conflicts are clerical: two branches added an import, appended a
dependency, added an entry to the same list, or reformatted whitespace. Those
are resolved here — deterministically, with no model call and no ambiguity.
Anything semantic (both sides rewrote the same logic) is deliberately left for
the LLM pass, which can read the surrounding code before deciding.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..repo_map import LOCKFILES
from .conflicts import ConflictBlock

#: Line shapes that are safe to union-merge when both sides only added lines.
_ADDITIVE_LINE_RES = [
    re.compile(r"^\s*(?:from\s+\S+\s+)?import\s+\S+"),          # python imports
    re.compile(r"^\s*(?:import|export)\s+.+from\s+['\"].+['\"];?\s*$"),  # js/ts imports
    re.compile(r"^\s*(?:const|let|var)\s+\w+\s*=\s*require\("),  # cjs imports
    re.compile(r"^\s*use\s+[\w:]+;"),                            # rust use
    re.compile(r"^\s*[\w.-]+\s*(?:[=<>~!]=|>=|<=|==)\s*[\w.*+-]+\s*$"),  # requirements pins
    re.compile(r"^\s*[\"']?[\w./@-]+[\"']?\s*:\s*[\"'][^\"']+[\"'],?\s*$"),  # json/yaml entries
    re.compile(r"^\s*-\s+\S+"),                                  # yaml list items
    re.compile(r"^\s*[\"'][^\"']+[\"'],\s*$"),                   # list-of-strings entries
]


@dataclass
class Resolution:
    """The outcome of trying to resolve one conflict block."""

    lines: list[str] | None
    strategy: str
    confidence: str = "high"
    note: str = ""

    @property
    def resolved(self) -> bool:
        return self.lines is not None


def _strip(lines: list[str]) -> list[str]:
    return [line.rstrip() for line in lines if line.strip()]


def _looks_additive(lines: list[str]) -> bool:
    meaningful = _strip(lines)
    if not meaningful:
        return True
    return all(any(pattern.match(line) for pattern in _ADDITIVE_LINE_RES) for line in meaningful)


def _union(ours: list[str], theirs: list[str]) -> list[str]:
    """Concatenate both sides, dropping duplicates while preserving order."""
    merged: list[str] = []
    seen: set[str] = set()
    for line in [*ours, *theirs]:
        key = line.strip()
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        merged.append(line)
    return merged


def resolve_block(
    block: ConflictBlock,
    *,
    path: str = "",
    prefer: str | None = None,
) -> Resolution:
    """Try to resolve one conflict without an LLM.

    ``prefer`` may be ``"ours"`` or ``"theirs"`` to force a side (used for
    generated files and explicit operator overrides).
    """
    ours, theirs = block.ours, block.theirs

    if prefer == "ours":
        return Resolution(list(ours), "forced-ours", note="operator preference")
    if prefer == "theirs":
        return Resolution(list(theirs), "forced-theirs", note="operator preference")

    if ours == theirs:
        return Resolution(list(ours), "identical")

    if _strip(ours) == _strip(theirs):
        # Same code, different trailing whitespace/blank lines: keep ours.
        return Resolution(list(ours), "whitespace-only")

    if not _strip(ours):
        return Resolution(list(theirs), "ours-empty")
    if not _strip(theirs):
        return Resolution(list(ours), "theirs-empty")

    ours_set, theirs_set = set(_strip(ours)), set(_strip(theirs))
    if ours_set < theirs_set:
        return Resolution(list(theirs), "theirs-superset")
    if theirs_set < ours_set:
        return Resolution(list(ours), "ours-superset")

    if block.base is not None:
        base_set = set(_strip(block.base))
        # Only one side actually changed relative to the merge base.
        if ours_set == base_set:
            return Resolution(list(theirs), "only-theirs-changed")
        if theirs_set == base_set:
            return Resolution(list(ours), "only-ours-changed")
        if base_set < ours_set and base_set < theirs_set and _looks_additive(ours + theirs):
            return Resolution(_union(ours, theirs), "additive-union-3way")

    if _looks_additive(ours) and _looks_additive(theirs):
        return Resolution(
            _union(ours, theirs),
            "additive-union",
            confidence="medium",
            note="both sides only added import/dependency/list lines",
        )

    if Path(path).name in LOCKFILES:
        return Resolution(
            None,
            "regenerate-lockfile",
            confidence="low",
            note=(
                f"{path} is a generated lockfile: resolve by taking the base branch "
                "version and re-running the package manager, not by hand-merging."
            ),
        )

    return Resolution(None, "needs-semantic-merge", confidence="low")


def resolve_blocks(
    blocks: list[ConflictBlock],
    *,
    path: str = "",
    prefer: str | None = None,
) -> tuple[dict[int, list[str]], list[tuple[int, Resolution]]]:
    """Resolve what we safely can; return resolutions and the leftovers."""
    resolutions: dict[int, list[str]] = {}
    unresolved: list[tuple[int, Resolution]] = []
    for index, block in enumerate(blocks):
        outcome = resolve_block(block, path=path, prefer=prefer)
        if outcome.resolved and outcome.lines is not None:
            resolutions[index] = outcome.lines
        else:
            unresolved.append((index, outcome))
    return resolutions, unresolved
