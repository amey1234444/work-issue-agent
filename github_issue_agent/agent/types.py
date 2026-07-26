"""Provider-neutral conversation types used by the agent loop."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Role = Literal["user", "assistant", "tool"]


@dataclass
class ToolCall:
    """A model request to run one tool."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def describe(self) -> str:
        rendered = json.dumps(self.arguments, ensure_ascii=False)
        if len(rendered) > 200:
            rendered = rendered[:200] + " ..."
        return f"{self.name}({rendered})"


@dataclass
class Message:
    """One conversation turn.

    ``tool_calls`` is only set on assistant turns; ``tool_call_id``/``name`` only
    on tool result turns.
    """

    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None

    def approx_tokens(self) -> int:
        size = len(self.content)
        for call in self.tool_calls:
            size += len(json.dumps(call.arguments)) + len(call.name)
        return max(1, size // 4)


@dataclass
class AssistantTurn:
    """What a provider returned for one step of the loop."""

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)

    def as_message(self) -> Message:
        return Message(role="assistant", content=self.text, tool_calls=list(self.tool_calls))


class ConversingProvider(Protocol):
    """An LLM provider that supports multi-turn tool calling."""

    def converse(  # pragma: no cover - interface
        self,
        system: str,
        messages: list[Message],
        tools: list[dict[str, Any]],
    ) -> AssistantTurn:
        ...
