"""Merge-conflict detection and automatic resolution."""

from .conflicts import (
    ConflictBlock,
    ConflictedFile,
    ConflictParseError,
    has_conflict_markers,
    parse_conflicts,
)
from .resolver import (
    FileOutcome,
    ResolutionResult,
    detect_conflicts,
    resolve_conflicts,
    resolve_file,
    sync_with_base,
)
from .strategies import Resolution, resolve_block, resolve_blocks

__all__ = [
    "ConflictBlock",
    "ConflictParseError",
    "ConflictedFile",
    "FileOutcome",
    "Resolution",
    "ResolutionResult",
    "detect_conflicts",
    "has_conflict_markers",
    "parse_conflicts",
    "resolve_block",
    "resolve_blocks",
    "resolve_conflicts",
    "resolve_file",
    "sync_with_base",
]
