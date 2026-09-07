"""One canonical path policy for every read, search, edit and backup.

All code that touches a repository-relative path goes through :class:`PathPolicy`
so the same rules apply everywhere: no absolute paths, no ``..`` escapes, no
symlinks that resolve outside the workspace, no Git internals and no files that
match the protected/secret patterns (``.env``, key material, ...).
"""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

DEFAULT_PROTECTED_PATTERNS: tuple[str, ...] = (
    ".git",
    ".git/**",
    ".env",
    ".env.*",
    "**/.env",
    "**/.env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "**/*.pem",
    "**/*.key",
    "**/id_rsa*",
    "**/id_ed25519*",
    ".ssh/**",
    "**/credentials.json",
    "**/service-account*.json",
    ".agent_work/**",
)


class PathPolicyError(ValueError):
    """The path is not allowed by policy."""


@dataclass
class PathPolicy:
    root: Path
    protected: tuple[str, ...] = field(default_factory=lambda: DEFAULT_PROTECTED_PATTERNS)

    def __post_init__(self) -> None:
        self.root = Path(self.root).resolve()

    # -- classification ------------------------------------------------------
    def is_protected(self, rel: str) -> bool:
        posix = PurePosixPath(rel.replace(os.sep, "/")).as_posix()
        for pattern in self.protected:
            if fnmatch.fnmatchcase(posix, pattern):
                return True
            # ``.git`` should also match ``.git/anything`` and ``**`` patterns
            # should match a bare top-level name.
            if pattern.endswith("/**") and posix == pattern[:-3]:
                return True
            if pattern.startswith("**/") and fnmatch.fnmatchcase(posix, pattern[3:]):
                return True
        return False

    def is_within_root(self, target: Path) -> bool:
        return target == self.root or self.root in target.parents

    # -- resolution ----------------------------------------------------------
    def resolve(self, rel: str, *, allow_protected: bool = False) -> Path:
        """Return the absolute, symlink-resolved path for ``rel`` or raise.

        Every parent that already exists is resolved through symlinks so a link
        inside the workspace cannot be used to reach a file outside it. The
        leaf itself is also resolved when it exists.
        """
        if not rel or rel.strip() != rel:
            raise PathPolicyError(f"Invalid path: {rel!r}")
        rel_path = Path(rel)
        if rel_path.is_absolute() or rel.startswith(("/", "\\")) or rel_path.drive:
            raise PathPolicyError(f"Absolute paths are not allowed: {rel!r}")
        if ".." in rel_path.parts:
            raise PathPolicyError(f"Path escapes the workspace: {rel!r}")
        if not allow_protected and self.is_protected(rel_path.as_posix()):
            raise PathPolicyError(f"Path is protected by policy: {rel!r}")

        candidate = self.root / rel_path
        # Resolve the deepest existing ancestor so symlinked directories are caught.
        existing = candidate
        while not existing.exists() and existing != self.root:
            existing = existing.parent
        resolved_existing = existing.resolve()
        if not self.is_within_root(resolved_existing):
            raise PathPolicyError(f"Path resolves outside the workspace: {rel!r}")
        if candidate.exists() and candidate.is_symlink():
            real = candidate.resolve()
            if not self.is_within_root(real):
                raise PathPolicyError(f"Symlink resolves outside the workspace: {rel!r}")
        remainder = candidate.relative_to(existing)
        target = resolved_existing / remainder
        if not self.is_within_root(target):
            raise PathPolicyError(f"Path resolves outside the workspace: {rel!r}")
        # The relative path after resolution must still not be protected (a
        # symlink named ``notes.md`` pointing at ``.env`` for example).
        resolved_rel = target.relative_to(self.root).as_posix()
        if not allow_protected and resolved_rel != "." and self.is_protected(resolved_rel):
            raise PathPolicyError(f"Path resolves to a protected file: {rel!r}")
        return target

    def check(self, rel: str) -> bool:
        try:
            self.resolve(rel)
        except PathPolicyError:
            return False
        return True
