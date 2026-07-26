"""Tool protocol shared by every agent tool.

A tool is a small, well-described capability the model can call during the agent
loop. Each tool owns its JSON schema so the same definition can be handed to
OpenAI-style function calling, Anthropic tool use, or the text fallback
protocol.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


class ToolError(RuntimeError):
    """Raised when a tool cannot run. The message is returned to the model."""


@dataclass
class ToolContext:
    """Everything a tool is allowed to touch during a run."""

    repo_path: Path
    #: Full command outputs, keyed by ``command_id``; kept out of the LLM context.
    command_outputs: dict[str, str] = field(default_factory=dict)
    #: Extra shell commands the operator explicitly approved for this run.
    extra_allowed_commands: list[str] = field(default_factory=list)
    #: Paths (repo-relative) touched by ``apply_patch`` during the run.
    patched_paths: list[str] = field(default_factory=list)
    network_enabled: bool = False

    def resolve(self, rel: str) -> Path:
        """Resolve a repo-relative path, refusing anything escaping the root."""
        root = self.repo_path.resolve()
        target = (root / rel).resolve()
        if target != root and root not in target.parents:
            raise ToolError(f"Path escapes the repository root: {rel!r}")
        return target


class Tool(Protocol):
    name: str
    description: str
    parameters: dict[str, Any]

    @property
    def run(self) -> Callable[..., str]:
        """``run(ctx, **arguments) -> str``.

        Declared as a callable attribute rather than a method so each tool can
        name its own keyword arguments, which the registry validates against
        ``parameters`` before calling.
        """


def schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def truncated_block(
    body: str,
    *,
    returned_lines: str,
    total_lines: int,
    hint: str,
) -> str:
    """Wrap output that had to be cut so the model always knows more exists."""
    return (
        f'<tool_output truncated="true" returned_lines="{returned_lines}" '
        f'total_lines="{total_lines}">\n{body}\n{hint}\n</tool_output>'
    )
