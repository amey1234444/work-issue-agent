"""The Codex-style agent loop.

One continuous conversation investigates, patches, validates and reports. Tool
calls and their results are appended to the same transcript, so the reasoning
that selected a file is still present when a test fails twenty steps later.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..llm import LLMProvider
from ..tools import PlanBoard, ToolContext, ToolRegistry, default_registry
from .completion_gate import FinalReport, GateResult, check_completion, parse_final_report
from .state import ConversationState
from .text_protocol import TextProtocolProvider
from .types import AssistantTurn, Message

EventHandler = Callable[[str, str], None]

#: Tool calls a single run may make before we stop, to bound cost.
DEFAULT_MAX_STEPS = 60

#: How many times the completion gate may bounce a premature final report.
MAX_GATE_RETRIES = 2


class AgentLoopError(RuntimeError):
    pass


@dataclass
class LoopResult:
    """Everything the harness needs after the model stops calling tools."""

    report: FinalReport
    steps: int
    tool_calls: list[str] = field(default_factory=list)
    validation_runs: list[tuple[str, bool]] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    diff: str = ""
    gate: GateResult | None = None
    compactions: int = 0

    @property
    def validated(self) -> bool:
        return bool(self.gate and self.gate.passed)


def ensure_conversing(provider: LLMProvider):
    """Return a provider that can do tool calling, wrapping it if necessary."""
    if hasattr(provider, "converse"):
        return provider
    return TextProtocolProvider(provider)


def _working_tree_diff(repo_path: Path, patched: list[str] | None = None) -> str:
    tracked = subprocess.run(
        ["git", "--no-pager", "diff", "HEAD"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    ).stdout
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if untracked:
        tracked += "\n" + "\n".join(f"+++ b/{path}\n(new file)" for path in untracked.splitlines())
    if not tracked.strip() and patched:
        # Not a git checkout: fall back to what apply_patch reported touching.
        tracked = "\n".join(f"+++ b/{path}\n(patched)" for path in patched)
    return tracked


def _is_validation_command(command: str) -> bool:
    return any(
        token in command
        for token in ("pytest", "test", "ruff", "mypy", "lint", "tsc", "eslint", "vitest", "jest")
    )


class AgentLoop:
    """Drive one model conversation until it produces a verified final report."""

    def __init__(
        self,
        provider: LLMProvider,
        *,
        repo_path: Path,
        system_prompt: str,
        registry: ToolRegistry | None = None,
        plan_board: PlanBoard | None = None,
        max_steps: int = DEFAULT_MAX_STEPS,
        require_validation: bool = True,
        require_changes: bool = True,
        on_event: EventHandler | None = None,
        extra_allowed_commands: list[str] | None = None,
    ):
        self.provider = ensure_conversing(provider)
        self.repo_path = repo_path
        self.system_prompt = system_prompt
        self.plan_board = plan_board or PlanBoard()
        self.registry = registry or default_registry(self.plan_board)
        self.max_steps = max_steps
        self.require_validation = require_validation
        self.require_changes = require_changes
        self.on_event = on_event
        self.ctx = ToolContext(
            repo_path=repo_path,
            extra_allowed_commands=list(extra_allowed_commands or []),
        )
        self.state = ConversationState()

    def _emit(self, kind: str, message: str) -> None:
        if self.on_event is not None:
            self.on_event(kind, message)

    def _execute(self, turn: AssistantTurn) -> list[Message]:
        results: list[Message] = []
        for call in turn.tool_calls:
            self._emit("tool", call.describe())
            output = self.registry.invoke(self.ctx, call.name, call.arguments)
            results.append(
                Message(
                    role="tool",
                    content=output,
                    tool_call_id=call.id,
                    name=call.name,
                )
            )
        return results

    def run(self, initial_message: str) -> LoopResult:
        self.state.add(Message(role="user", content=initial_message))
        tool_calls: list[str] = []
        validation_runs: list[tuple[str, bool]] = []
        steps = 0
        gate_retries = 0
        turn = AssistantTurn()

        while steps < self.max_steps:
            self.state.compact_if_needed()
            turn = self.provider.converse(
                self.system_prompt,
                self.state.messages,
                self.registry.specs(),
            )
            self.state.add(turn.as_message())

            if turn.wants_tools:
                steps += len(turn.tool_calls)
                for call in turn.tool_calls:
                    tool_calls.append(call.describe())
                outputs = self._execute(turn)
                for call, message in zip(turn.tool_calls, outputs, strict=False):
                    if call.name == "run_command":
                        command = " ".join(
                            call.arguments.get("command", [])
                            if isinstance(call.arguments.get("command"), list)
                            else [str(call.arguments.get("command", ""))]
                        )
                        passed = "<validation_result>" not in message.content and not (
                            message.content.startswith("ERROR")
                        )
                        if _is_validation_command(command):
                            validation_runs.append((command, passed))
                self.state.extend(outputs)
                continue

            # No tool calls: the model believes it is finished.
            diff = _working_tree_diff(self.repo_path, self.ctx.patched_paths)
            gate = check_completion(
                diff=diff,
                validation_runs=validation_runs,
                require_validation=self.require_validation,
                require_changes=self.require_changes,
            )
            if not gate.passed and gate_retries >= MAX_GATE_RETRIES:
                raise AgentLoopError(
                    "The agent could not satisfy the completion contract:\n  - "
                    + "\n  - ".join(gate.problems)
                )
            if gate.passed:
                report = parse_final_report(turn.text)
                if gate.warnings:
                    self._emit("integrity", "\n".join(gate.warnings))
                return LoopResult(
                    report=report,
                    steps=steps,
                    tool_calls=tool_calls,
                    validation_runs=validation_runs,
                    changed_files=list(self.ctx.patched_paths),
                    diff=diff,
                    gate=gate,
                    compactions=self.state.compactions,
                )
            gate_retries += 1
            self._emit("gate", "; ".join(gate.problems))
            self.state.add(Message(role="user", content=gate.as_feedback()))

        raise AgentLoopError(
            f"Agent exceeded the maximum of {self.max_steps} tool calls without finishing. "
            "Increase --max-steps or narrow the task."
        )
