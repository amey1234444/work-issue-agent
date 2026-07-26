"""Tool calling for providers that only support plain text completion.

Many cheap/free models (and every OpenRouter model without function-calling
support) can still follow a strict JSON protocol. This adapter renders the tool
schemas into the system prompt, flattens the conversation into a transcript, and
parses the model's reply back into :class:`ToolCall` objects — so the agent loop
works identically regardless of provider capability.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from ..llm import LLMProvider
from .types import AssistantTurn, Message, ToolCall

_PROTOCOL = """# Tool protocol

You do not have native tool calling, so you must use this text protocol.

To call tools, reply with ONLY a JSON object (no prose, no code fences):
{"tool_calls": [{"name": "<tool>", "arguments": {...}}]}

To finish, reply with ONLY:
{"final": "<your final answer>"}

Call at most two tools per reply. Never mix prose with the JSON object."""


def render_tools(tools: list[dict[str, Any]]) -> str:
    blocks = []
    for tool in tools:
        blocks.append(
            f"## {tool['name']}\n{tool['description']}\n"
            f"parameters: {json.dumps(tool['parameters'])}"
        )
    return "# Available tools\n\n" + "\n\n".join(blocks)


def render_transcript(messages: list[Message]) -> str:
    parts: list[str] = []
    for message in messages:
        if message.role == "user":
            parts.append(f"<user>\n{message.content}\n</user>")
        elif message.role == "assistant":
            calls = ", ".join(call.describe() for call in message.tool_calls)
            body = message.content or ""
            if calls:
                body = f"{body}\n[called: {calls}]".strip()
            parts.append(f"<assistant>\n{body}\n</assistant>")
        else:
            parts.append(
                f'<tool_result name="{message.name}" id="{message.tool_call_id}">\n'
                f"{message.content}\n</tool_result>"
            )
    return "\n\n".join(parts)


def _extract_json(text: str) -> dict[str, Any] | None:
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1)
    start = cleaned.find("{")
    if start == -1:
        return None
    depth = 0
    for index in range(start, len(cleaned)):
        char = cleaned[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(cleaned[start : index + 1])
                except json.JSONDecodeError:
                    return None
                return parsed if isinstance(parsed, dict) else None
    return None


def parse_turn(text: str) -> AssistantTurn:
    """Parse a text reply into a tool-calling turn (or a final answer)."""
    data = _extract_json(text)
    if not data:
        return AssistantTurn(text=text)
    if isinstance(data.get("tool_calls"), list):
        turn = AssistantTurn(text=str(data.get("thinking", "")))
        for raw in data["tool_calls"]:
            if not isinstance(raw, dict) or "name" not in raw:
                continue
            arguments = raw.get("arguments") or raw.get("parameters") or {}
            if isinstance(arguments, str):
                arguments = _extract_json(arguments) or {}
            turn.tool_calls.append(
                ToolCall(
                    id=str(raw.get("id") or uuid.uuid4().hex[:8]),
                    name=str(raw["name"]),
                    arguments=arguments if isinstance(arguments, dict) else {},
                )
            )
        if turn.tool_calls:
            return turn
    if "final" in data:
        return AssistantTurn(text=str(data["final"]))
    if "name" in data:  # a bare single tool call
        arguments = data.get("arguments") or {}
        return AssistantTurn(
            tool_calls=[
                ToolCall(
                    id=uuid.uuid4().hex[:8],
                    name=str(data["name"]),
                    arguments=arguments if isinstance(arguments, dict) else {},
                )
            ]
        )
    return AssistantTurn(text=text)


class TextProtocolProvider:
    """Wrap a ``complete``-only provider so it can drive the agent loop."""

    def __init__(self, inner: LLMProvider):
        self.inner = inner

    def complete(self, system: str, user: str) -> str:
        return self.inner.complete(system, user)

    def converse(
        self,
        system: str,
        messages: list[Message],
        tools: list[dict[str, Any]],
    ) -> AssistantTurn:
        full_system = f"{system}\n\n{render_tools(tools)}\n\n{_PROTOCOL}"
        transcript = render_transcript(messages)
        return parse_turn(self.inner.complete(full_system, transcript))
