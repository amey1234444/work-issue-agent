"""LLM provider abstraction.

Supports Anthropic, OpenAI and a deterministic ``mock`` provider (no API key
needed) so the whole pipeline can be exercised offline. SDKs are imported lazily
so the package installs without them.

Providers expose two capabilities:

``complete``
    one-shot prompt in, text out (used by the legacy plan/implement workflow);
``converse``
    multi-turn tool calling (used by the Codex-style agent loop). Providers
    without native tool calling are wrapped by
    :class:`~github_issue_agent.agent.text_protocol.TextProtocolProvider`.
"""

from __future__ import annotations

import json
import os
import uuid
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from .config import Config

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .agent.types import AssistantTurn, Message


class LLMError(RuntimeError):
    pass


class LLMProvider(Protocol):
    def complete(self, system: str, user: str) -> str:  # pragma: no cover - interface
        ...


@runtime_checkable
class ToolCallingProvider(Protocol):
    """A provider with native function/tool calling support."""

    def converse(  # pragma: no cover - interface
        self,
        system: str,
        messages: list[Message],
        tools: list[dict[str, Any]],
    ) -> AssistantTurn:
        ...


class AnthropicProvider:
    def __init__(self, model: str):
        try:
            import anthropic  # noqa: F401
        except ImportError as exc:  # pragma: no cover - depends on install
            raise LLMError(
                "The 'anthropic' package is not installed. Install with: pip install 'github-issue-agent[anthropic]'"
            ) from exc
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise LLMError("ANTHROPIC_API_KEY is not set.")
        from anthropic import Anthropic

        self._client = Anthropic(api_key=api_key)
        self._model = model

    def complete(self, system: str, user: str) -> str:
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=8192,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        parts: list[str] = []
        for block in resp.content:
            if block.type == "text":
                parts.append(block.text)
        return "\n".join(parts)

    def converse(
        self,
        system: str,
        messages: list[Message],
        tools: list[dict[str, Any]],
    ) -> AssistantTurn:
        from .agent.types import AssistantTurn, ToolCall

        payload: list[dict[str, Any]] = []
        for message in messages:
            if message.role == "tool":
                payload.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": message.tool_call_id,
                                "content": message.content,
                            }
                        ],
                    }
                )
            elif message.role == "assistant":
                blocks: list[dict[str, Any]] = []
                if message.content:
                    blocks.append({"type": "text", "text": message.content})
                for call in message.tool_calls:
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": call.id,
                            "name": call.name,
                            "input": call.arguments,
                        }
                    )
                payload.append({"role": "assistant", "content": blocks or [{"type": "text", "text": ""}]})
            else:
                payload.append({"role": "user", "content": message.content})

        resp = self._client.messages.create(
            model=self._model,
            max_tokens=8192,
            system=system,
            messages=payload,
            tools=[
                {
                    "name": tool["name"],
                    "description": tool["description"],
                    "input_schema": tool["parameters"],
                }
                for tool in tools
            ],
        )
        turn = AssistantTurn()
        texts: list[str] = []
        for block in resp.content:
            if block.type == "text":
                texts.append(block.text)
            elif block.type == "tool_use":
                turn.tool_calls.append(
                    ToolCall(id=block.id, name=block.name, arguments=dict(block.input or {}))
                )
        turn.text = "\n".join(texts)
        return turn


class OpenAIProvider:
    """OpenAI Chat Completions, also used for any OpenAI-compatible endpoint."""

    def __init__(self, model: str, *, api_key_env: str = "OPENAI_API_KEY", base_url: str | None = None):
        try:
            import openai  # noqa: F401
        except ImportError as exc:  # pragma: no cover - depends on install
            raise LLMError(
                "The 'openai' package is not installed. Install with: pip install 'github-issue-agent[openai]'"
            ) from exc
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise LLMError(f"{api_key_env} is not set.")
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self._base_url = base_url or ""

    def complete(self, system: str, user: str) -> str:
        kwargs: dict = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": 8192,
        }
        # OpenRouter exposes a `reasoning` control; disabling it stops reasoning
        # models (e.g. GLM, Qwen3) from spending the whole budget "thinking" and
        # returning empty content. Ignored by non-OpenRouter endpoints.
        if "openrouter" in self._base_url:
            kwargs["extra_body"] = {"reasoning": {"enabled": False}}
        resp = self._client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""

    def converse(
        self,
        system: str,
        messages: list[Message],
        tools: list[dict[str, Any]],
    ) -> AssistantTurn:
        from .agent.types import AssistantTurn, ToolCall

        payload: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for message in messages:
            if message.role == "tool":
                payload.append(
                    {
                        "role": "tool",
                        "tool_call_id": message.tool_call_id,
                        "content": message.content,
                    }
                )
            elif message.role == "assistant":
                entry: dict[str, Any] = {"role": "assistant", "content": message.content or None}
                if message.tool_calls:
                    entry["tool_calls"] = [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json.dumps(call.arguments),
                            },
                        }
                        for call in message.tool_calls
                    ]
                payload.append(entry)
            else:
                payload.append({"role": "user", "content": message.content})

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": payload,
            "max_tokens": 8192,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": tool["parameters"],
                    },
                }
                for tool in tools
            ],
        }
        resp = self._client.chat.completions.create(**kwargs)
        choice = resp.choices[0].message
        turn = AssistantTurn(text=getattr(choice, "content", None) or "")
        for call in getattr(choice, "tool_calls", None) or []:
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {"_raw_arguments": call.function.arguments}
            turn.tool_calls.append(
                ToolCall(
                    id=getattr(call, "id", None) or uuid.uuid4().hex[:8],
                    name=call.function.name,
                    arguments=arguments if isinstance(arguments, dict) else {},
                )
            )
        return turn


class MockProvider:
    """Deterministic provider for offline testing and demos.

    It inspects the prompt to decide whether a planning or coding response is
    expected and returns valid JSON for that step, and it can drive the agent
    loop through a fixed investigate -> patch -> report sequence.
    """

    def converse(
        self,
        system: str,
        messages: list[Message],
        tools: list[dict[str, Any]],
    ) -> AssistantTurn:
        from .agent.types import AssistantTurn, ToolCall

        called = {
            call.name
            for message in messages
            if message.role == "assistant"
            for call in message.tool_calls
        }
        if "list_files" not in called:
            return AssistantTurn(
                tool_calls=[ToolCall(id="1", name="list_files", arguments={"max_results": 20})]
            )
        if "apply_patch" not in called:
            patch = (
                "*** Begin Patch\n"
                "*** Add File: AGENT_NOTES.md\n"
                "+# Agent Notes\n"
                "+\n"
                "+This file was created by the mock provider to verify the end-to-end flow.\n"
                "*** End Patch\n"
            )
            return AssistantTurn(
                tool_calls=[ToolCall(id="2", name="apply_patch", arguments={"patch": patch})]
            )
        return AssistantTurn(
            text=(
                "SUMMARY: Mock implementation: documents the requested change.\n"
                "BRANCH: agent/mock-change\n"
                "COMMIT: docs: add agent notes (mock run)\n"
                "PR_TITLE: Mock change from work-issue-agent\n"
                "PR_BODY:\n"
                "This PR was generated by the mock provider for testing the pipeline.\n"
                "VALIDATION: none required (mock run)"
            )
        )

    def complete(self, system: str, user: str) -> str:
        if "PLANNING" in system or "files_to_read" in system:
            return json.dumps(
                {
                    "understanding": "Mock understanding of the request.",
                    "files_to_read": [],
                    "steps": ["Add an AGENT_NOTES.md documenting the requested change."],
                }
            )
        return json.dumps(
            {
                "summary": "Mock implementation: documents the requested change.",
                "branch": "agent/mock-change",
                "commit_message": "docs: add agent notes (mock run)",
                "pr_title": "Mock change from work-issue-agent",
                "pr_body": "This PR was generated by the mock LLM provider for testing the pipeline.",
                "edits": [
                    {
                        "path": "AGENT_NOTES.md",
                        "action": "create",
                        "content": "# Agent Notes\n\nThis file was created by the mock provider to verify the end-to-end flow.\n",
                    }
                ],
                "commands": [],
            }
        )


def get_provider(config: Config) -> LLMProvider:
    provider = config.provider
    if provider == "anthropic":
        return AnthropicProvider(config.anthropic_model)
    if provider == "openai":
        return OpenAIProvider(config.openai_model)
    if provider == "openrouter":
        return OpenAIProvider(
            config.openrouter_model,
            api_key_env="OPENROUTER_API_KEY",
            base_url=config.openrouter_base_url,
        )
    if provider == "mock":
        return MockProvider()
    raise LLMError(
        f"Unknown LLM_PROVIDER: {provider!r} (expected anthropic|openai|openrouter|mock)"
    )
