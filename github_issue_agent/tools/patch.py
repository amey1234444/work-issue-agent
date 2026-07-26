"""The repository-mutating tools: ``apply_patch`` and ``get_git_diff``."""

from __future__ import annotations

import subprocess
from typing import Any

from ..patcher import PatchError, parse_patch
from ..patcher import apply_patch as apply_patch_text
from .base import ToolContext, ToolError, schema, truncated_block

PATCH_FORMAT_HELP = """Patch envelope format:

*** Begin Patch
*** Update File: path/to/file.py
@@
 unchanged context line
-line to remove
+line to add
*** Add File: path/to/new_file.py
+first line of the new file
*** Delete File: path/to/obsolete.py
*** End Patch

Rules: context lines start with a single space, additions with '+', removals
with '-'. Give at least three lines of surrounding context so the hunk is
unambiguous. Never paste a whole file when a few lines change."""

_MAX_DIFF_LINES = 400


class ApplyPatchTool:
    name = "apply_patch"
    description = (
        "Apply a context diff to the repository. THIS TOOL MODIFIES FILES. "
        "Make one focused change per call, re-read a file first if a previous "
        "hunk failed, and never rewrite a whole file when a few lines change. "
        "The patch is applied atomically: if any hunk fails, nothing is written "
        "and the error tells you why.\n\n" + PATCH_FORMAT_HELP
    )
    parameters = schema(
        {"patch": {"type": "string", "description": "The full '*** Begin Patch' envelope"}},
        ["patch"],
    )

    def run(self, ctx: ToolContext, *, patch: str, **_: Any) -> str:
        try:
            operations = parse_patch(patch)
            results = apply_patch_text(ctx.repo_path, patch)
        except PatchError as exc:
            raise ToolError(f"Patch failed (no changes were written): {exc}") from exc
        for op in operations:
            if op.path not in ctx.patched_paths:
                ctx.patched_paths.append(op.path)
        return "Patch applied:\n" + "\n".join(f"  {line}" for line in results)


class GetGitDiffTool:
    name = "get_git_diff"
    description = (
        "Show the current uncommitted diff of the working tree, so you can review "
        "exactly what you changed before finishing. Optionally scope it to one "
        "path. This tool never modifies the repository."
    )
    parameters = schema(
        {
            "path": {"type": "string"},
            "stat_only": {"type": "boolean", "description": "Return only a summary of files"},
        },
        [],
    )

    def run(
        self,
        ctx: ToolContext,
        *,
        path: str | None = None,
        stat_only: bool = False,
        **_: Any,
    ) -> str:
        args = ["git", "--no-pager", "diff", "HEAD"]
        if stat_only:
            args.append("--stat")
        if path:
            ctx.resolve(path)
            args += ["--", path]
        proc = subprocess.run(args, cwd=ctx.repo_path, capture_output=True, text=True)
        if proc.returncode not in (0, 1):
            raise ToolError(f"git diff failed: {proc.stderr.strip()}")
        # Untracked files are invisible to `git diff`; list them so newly created
        # files are never missing from the review.
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=ctx.repo_path,
            capture_output=True,
            text=True,
        ).stdout.strip()
        diff = proc.stdout or "(no tracked changes)"
        if untracked:
            diff += "\n\nUntracked new files:\n" + untracked
        lines = diff.splitlines()
        if len(lines) > _MAX_DIFF_LINES:
            return truncated_block(
                "\n".join(lines[:_MAX_DIFF_LINES]),
                returned_lines=f"1-{_MAX_DIFF_LINES}",
                total_lines=len(lines),
                hint="Call get_git_diff(stat_only=true) or scope it with 'path'.",
            )
        return diff
