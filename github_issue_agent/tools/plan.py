"""``update_plan``: the model's externalised, always-visible TODO list."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .base import ToolContext, ToolError, schema

_STATES = {"pending", "in_progress", "completed"}


@dataclass
class PlanStep:
    step: str
    status: str = "pending"


@dataclass
class PlanBoard:
    """Mutable plan shared between the loop and the ``update_plan`` tool."""

    steps: list[PlanStep] = field(default_factory=list)

    def as_text(self) -> str:
        if not self.steps:
            return "(no plan yet)"
        marks = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}
        return "\n".join(
            f"  {marks.get(s.status, '[ ]')} {s.step}" for s in self.steps
        )

    @property
    def complete(self) -> bool:
        return bool(self.steps) and all(s.status == "completed" for s in self.steps)


class UpdatePlanTool:
    name = "update_plan"
    description = (
        "Record or revise your implementation plan. Call it once after "
        "investigating, then again whenever a step completes or the plan changes. "
        "Keep steps short and verifiable. This tool never modifies the repository."
    )
    parameters = schema(
        {
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "step": {"type": "string"},
                        "status": {"type": "string", "enum": sorted(_STATES)},
                    },
                    "required": ["step"],
                    "additionalProperties": False,
                },
            }
        },
        ["steps"],
    )

    def __init__(self, board: PlanBoard):
        self.board = board

    def run(self, ctx: ToolContext, *, steps: list[dict[str, Any]], **_: Any) -> str:
        if not isinstance(steps, list) or not steps:
            raise ToolError("steps must be a non-empty list")
        parsed: list[PlanStep] = []
        for item in steps:
            if isinstance(item, str):
                parsed.append(PlanStep(step=item))
                continue
            step = str(item.get("step", "")).strip()
            if not step:
                raise ToolError("every plan item needs a non-empty 'step'")
            status = str(item.get("status", "pending"))
            if status not in _STATES:
                raise ToolError(f"invalid status {status!r}; use one of {sorted(_STATES)}")
            parsed.append(PlanStep(step=step, status=status))
        self.board.steps = parsed
        return "Plan updated:\n" + self.board.as_text()
