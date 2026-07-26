"""Code search tools: ``search_code``, ``find_symbol`` and ``find_references``."""

from __future__ import annotations

import fnmatch
import re
from typing import Any

from ..repo_map import build_repo_map, iter_repo_files
from .base import ToolContext, ToolError, schema

_MAX_MATCH_CHARS = 300


def _iter_lines(ctx: ToolContext, path_glob: str | None) -> list[tuple[str, list[str]]]:
    files = iter_repo_files(ctx.repo_path)
    if path_glob:
        files = [f for f in files if fnmatch.fnmatch(f, path_glob)]
    out: list[tuple[str, list[str]]] = []
    for rel in files:
        try:
            text = (ctx.repo_path / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        out.append((rel, text.splitlines()))
    return out


def _format_hits(hits: list[tuple[str, int, str]], limit: int, header: str) -> str:
    if not hits:
        return f"{header}\n(no matches)"
    lines = [header]
    for rel, number, text in hits[:limit]:
        snippet = text.strip()
        if len(snippet) > _MAX_MATCH_CHARS:
            snippet = snippet[:_MAX_MATCH_CHARS] + " ..."
        lines.append(f"{rel}:{number}: {snippet}")
    if len(hits) > limit:
        lines.append(f"... [{len(hits) - limit} more matches; refine query or path_glob]")
    return "\n".join(lines)


class SearchCodeTool:
    name = "search_code"
    description = (
        "Search tracked repository files for text, symbols, error strings, "
        "configuration keys or test names. Returns 'path:line: match' rows, never "
        "whole files. Use it before read_file to locate relevant code. "
        "This tool never modifies the repository."
    )
    parameters = schema(
        {
            "query": {"type": "string", "description": "Literal text or regex to find"},
            "path_glob": {"type": "string", "description": "e.g. 'src/**/*.py'"},
            "regex": {"type": "boolean", "description": "Treat query as a regex"},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 50},
        },
        ["query"],
    )

    def run(
        self,
        ctx: ToolContext,
        *,
        query: str,
        path_glob: str | None = None,
        regex: bool = False,
        max_results: int = 30,
        **_: Any,
    ) -> str:
        if not query.strip():
            raise ToolError("query must not be empty")
        limit = max(1, min(int(max_results), 50))
        try:
            pattern = re.compile(query if regex else re.escape(query), re.IGNORECASE)
        except re.error as exc:
            raise ToolError(f"Invalid regex: {exc}") from exc

        hits: list[tuple[str, int, str]] = []
        for rel, lines in _iter_lines(ctx, path_glob):
            for number, line in enumerate(lines, start=1):
                if pattern.search(line):
                    hits.append((rel, number, line))
        return _format_hits(hits, limit, f"search_code({query!r}) -> {len(hits)} match(es)")


class FindSymbolTool:
    name = "find_symbol"
    description = (
        "Locate where a class, function or method is DEFINED. Prefer this over "
        "search_code when you know the symbol name. "
        "This tool never modifies the repository."
    )
    parameters = schema(
        {
            "name": {"type": "string"},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 50},
        },
        ["name"],
    )

    def run(self, ctx: ToolContext, *, name: str, max_results: int = 20, **_: Any) -> str:
        limit = max(1, min(int(max_results), 50))
        escaped = re.escape(name)
        definition = re.compile(
            rf"^\s*(?:export\s+)?(?:async\s+)?(?:def|class|function|fn|struct|enum|trait|"
            rf"interface|type)\s+{escaped}\b"
            rf"|^\s*(?:export\s+)?(?:const|let|var)\s+{escaped}\s*="
            rf"|^\s*func\s+(?:\([^)]*\)\s*)?{escaped}\b"
        )
        hits: list[tuple[str, int, str]] = []
        for rel, lines in _iter_lines(ctx, None):
            for number, line in enumerate(lines, start=1):
                if definition.search(line):
                    hits.append((rel, number, line))
        if not hits:
            # Fall back to the indexed symbol table (catches methods and decorators).
            repo_map = build_repo_map(ctx.repo_path)
            rows = [
                f"{entry.path}: {sym}"
                for entry in repo_map.files
                for sym in entry.symbols
                if name in sym
            ]
            if rows:
                return "find_symbol (index match):\n" + "\n".join(rows[:limit])
        return _format_hits(hits, limit, f"find_symbol({name!r}) -> {len(hits)} definition(s)")


class FindReferencesTool:
    name = "find_references"
    description = (
        "Find call sites and other references to a symbol across the repository, "
        "excluding its definition lines. Use it to understand blast radius before "
        "changing a function. This tool never modifies the repository."
    )
    parameters = schema(
        {
            "name": {"type": "string"},
            "path_glob": {"type": "string"},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 50},
        },
        ["name"],
    )

    def run(
        self,
        ctx: ToolContext,
        *,
        name: str,
        path_glob: str | None = None,
        max_results: int = 30,
        **_: Any,
    ) -> str:
        limit = max(1, min(int(max_results), 50))
        usage = re.compile(rf"\b{re.escape(name)}\b")
        definition = re.compile(
            rf"^\s*(?:export\s+)?(?:async\s+)?(?:def|class|function|fn|func)\s+{re.escape(name)}\b"
        )
        hits: list[tuple[str, int, str]] = []
        for rel, lines in _iter_lines(ctx, path_glob):
            for number, line in enumerate(lines, start=1):
                if usage.search(line) and not definition.search(line):
                    hits.append((rel, number, line))
        return _format_hits(hits, limit, f"find_references({name!r}) -> {len(hits)} reference(s)")
