"""Filesystem inspection tools: ``list_files`` and ``read_file``."""

from __future__ import annotations

import fnmatch
from typing import Any

from ..repo_map import iter_repo_files
from .base import ToolContext, ToolError, schema, truncated_block

_MAX_READ_LINES = 400
_MAX_LINE_CHARS = 500


class ReadFileTool:
    name = "read_file"
    description = (
        "Read a UTF-8 text file from the repository, returned with line numbers. "
        "Use start_line/end_line for large files; at most 400 lines are returned "
        "per call and the response states when more content exists. "
        "This tool never modifies the repository."
    )
    parameters = schema(
        {
            "path": {"type": "string", "description": "Repository-relative file path"},
            "start_line": {"type": "integer", "minimum": 1},
            "end_line": {"type": "integer", "minimum": 1},
        },
        ["path"],
    )

    def run(
        self,
        ctx: ToolContext,
        *,
        path: str,
        start_line: int | None = None,
        end_line: int | None = None,
        **_: Any,
    ) -> str:
        target = ctx.resolve(path)
        if not target.is_file():
            raise ToolError(f"No such file: {path}")
        try:
            text = target.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ToolError(f"{path} is not a UTF-8 text file") from exc

        lines = text.splitlines()
        total = len(lines)
        start = max(1, start_line or 1)
        end = min(total, end_line or start + _MAX_READ_LINES - 1)
        if start > total:
            raise ToolError(f"{path} has only {total} lines; start_line={start} is out of range")
        capped = min(end, start + _MAX_READ_LINES - 1)

        body_lines = []
        for number in range(start, capped + 1):
            content = lines[number - 1]
            if len(content) > _MAX_LINE_CHARS:
                content = content[:_MAX_LINE_CHARS] + " ... [line truncated]"
            body_lines.append(f"{number:6d}| {content}")
        body = f'<file path="{path}" lines="{start}-{capped}" total_lines="{total}">\n'
        body += "\n".join(body_lines)
        body += "\n</file>"

        if capped < total:
            return truncated_block(
                body,
                returned_lines=f"{start}-{capped}",
                total_lines=total,
                hint=f"Use read_file(path={path!r}, start_line={capped + 1}) for more.",
            )
        return body


class ListFilesTool:
    name = "list_files"
    description = (
        "List tracked repository files, optionally filtered by a glob such as "
        "'src/**/*.py'. Returns paths only, never file contents. "
        "This tool never modifies the repository."
    )
    parameters = schema(
        {
            "path_glob": {"type": "string"},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 500},
        },
        [],
    )

    def run(
        self,
        ctx: ToolContext,
        *,
        path_glob: str | None = None,
        max_results: int = 200,
        **_: Any,
    ) -> str:
        max_results = max(1, min(int(max_results), 500))
        files = iter_repo_files(ctx.repo_path)
        if path_glob:
            files = [f for f in files if fnmatch.fnmatch(f, path_glob)]
        if not files:
            return "(no matching files)"
        shown = files[:max_results]
        out = "\n".join(shown)
        if len(files) > max_results:
            out += f"\n... [{len(files) - max_results} more files omitted; narrow path_glob]"
        return out
