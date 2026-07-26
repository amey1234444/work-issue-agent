"""Sandboxed command execution plus paged access to full command logs."""

from __future__ import annotations

import uuid
from typing import Any

from ..validation.commands import CommandNotAllowed
from ..validation.commands import run as run_approved
from ..validation.failure_parser import parse_failure
from .base import ToolContext, ToolError, schema, truncated_block

_MAX_OUTPUT_LINES = 120


class RunCommandTool:
    name = "run_command"
    description = (
        "Run one approved build, test, lint, type-check or inspection command in "
        "the repository sandbox. Pass argv as a list (no shell pipes or "
        "redirection). Output is truncated to the last 120 lines; failures come "
        "back as a structured report and the full log stays available through "
        "read_command_output. This tool CAN change the working tree (e.g. via a "
        "formatter), so prefer read-only commands while investigating."
    )
    parameters = schema(
        {
            "command": {"type": "array", "items": {"type": "string"}},
            "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 900},
        },
        ["command"],
    )

    def run(
        self,
        ctx: ToolContext,
        *,
        command: list[str] | str,
        timeout_seconds: int = 600,
        **_: Any,
    ) -> str:
        try:
            result = run_approved(
                ctx.repo_path,
                command,
                timeout=max(1, min(int(timeout_seconds), 900)),
                extra_allowed=ctx.extra_allowed_commands,
            )
        except CommandNotAllowed as exc:
            raise ToolError(str(exc)) from exc

        command_id = uuid.uuid4().hex[:8]
        ctx.command_outputs[command_id] = result.output

        if not result.ok:
            return parse_failure(result.command, result.exit_code, result.output, command_id).as_xml()

        lines = result.output.splitlines()
        header = f"$ {result.command}\nexit_code: 0\ncommand_id: {command_id}"
        if len(lines) <= _MAX_OUTPUT_LINES:
            return f"{header}\n" + "\n".join(lines)
        body = f"{header}\n" + "\n".join(lines[-_MAX_OUTPUT_LINES:])
        return truncated_block(
            body,
            returned_lines=f"{len(lines) - _MAX_OUTPUT_LINES + 1}-{len(lines)}",
            total_lines=len(lines),
            hint=f"Use read_command_output(command_id={command_id!r}, start_line=1) for more.",
        )


class ReadCommandOutputTool:
    name = "read_command_output"
    description = (
        "Read a line range from the full stored output of a previous run_command "
        "call. Use it when a truncated result hid the detail you need. "
        "This tool never modifies the repository."
    )
    parameters = schema(
        {
            "command_id": {"type": "string"},
            "start_line": {"type": "integer", "minimum": 1},
            "end_line": {"type": "integer", "minimum": 1},
        },
        ["command_id"],
    )

    def run(
        self,
        ctx: ToolContext,
        *,
        command_id: str,
        start_line: int = 1,
        end_line: int | None = None,
        **_: Any,
    ) -> str:
        if command_id not in ctx.command_outputs:
            known = ", ".join(ctx.command_outputs) or "(none)"
            raise ToolError(f"Unknown command_id {command_id!r}. Known ids: {known}")
        lines = ctx.command_outputs[command_id].splitlines()
        total = len(lines)
        start = max(1, int(start_line))
        end = min(total, end_line or start + 199)
        end = min(end, start + 199)
        if start > total:
            raise ToolError(f"Log has only {total} lines")
        body = "\n".join(lines[start - 1 : end])
        if end < total:
            return truncated_block(
                body,
                returned_lines=f"{start}-{end}",
                total_lines=total,
                hint=f"Use read_command_output({command_id!r}, start_line={end + 1}) for more.",
            )
        return body
