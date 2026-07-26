"""The tool layer the agent loop drives.

Tools are the only way the model touches the repository, which keeps every
action auditable, bounded in output size, and independent of the LLM provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .base import Tool, ToolContext, ToolError
from .fs import ListFilesTool, ReadFileTool
from .patch import ApplyPatchTool, GetGitDiffTool
from .plan import PlanBoard, PlanStep, UpdatePlanTool
from .search import FindReferencesTool, FindSymbolTool, SearchCodeTool
from .shell import ReadCommandOutputTool, RunCommandTool


@dataclass
class ToolRegistry:
    """Name -> tool lookup plus the JSON schemas handed to the provider."""

    tools: dict[str, Tool] = field(default_factory=dict)

    def register(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self.tools:
            raise ToolError(f"Unknown tool {name!r}. Available: {', '.join(sorted(self.tools))}")
        return self.tools[name]

    def specs(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            }
            for tool in self.tools.values()
        ]

    def invoke(self, ctx: ToolContext, name: str, arguments: dict[str, Any]) -> str:
        tool = self.get(name)
        try:
            return tool.run(ctx, **arguments)
        except ToolError as exc:
            return f"ERROR: {exc}"
        except TypeError as exc:
            return f"ERROR: invalid arguments for {name}: {exc}"
        except Exception as exc:  # pragma: no cover - defensive
            return f"ERROR: {type(exc).__name__}: {exc}"


def default_registry(plan_board: PlanBoard | None = None, *, read_only: bool = False) -> ToolRegistry:
    """Build the standard toolset. ``read_only`` omits mutating tools."""
    registry = ToolRegistry()
    for tool in (
        ListFilesTool(),
        ReadFileTool(),
        SearchCodeTool(),
        FindSymbolTool(),
        FindReferencesTool(),
        GetGitDiffTool(),
        ReadCommandOutputTool(),
        UpdatePlanTool(plan_board or PlanBoard()),
    ):
        registry.register(tool)
    if not read_only:
        registry.register(ApplyPatchTool())
        registry.register(RunCommandTool())
    return registry


__all__ = [
    "ApplyPatchTool",
    "FindReferencesTool",
    "FindSymbolTool",
    "GetGitDiffTool",
    "ListFilesTool",
    "PlanBoard",
    "PlanStep",
    "ReadCommandOutputTool",
    "ReadFileTool",
    "RunCommandTool",
    "SearchCodeTool",
    "Tool",
    "ToolContext",
    "ToolError",
    "ToolRegistry",
    "UpdatePlanTool",
    "default_registry",
]
