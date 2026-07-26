"""The Codex-style agent: one conversation, many tools, verified completion."""

from .completion_gate import FinalReport, GateResult, check_completion, parse_final_report
from .loop import AgentLoop, AgentLoopError, LoopResult, ensure_conversing
from .prompt import (
    CODING_AGENT_INSTRUCTIONS,
    MERGE_AGENT_INSTRUCTIONS,
    environment_block,
    initial_message,
)
from .state import ConversationState
from .text_protocol import TextProtocolProvider, parse_turn
from .types import AssistantTurn, Message, ToolCall

__all__ = [
    "CODING_AGENT_INSTRUCTIONS",
    "MERGE_AGENT_INSTRUCTIONS",
    "AgentLoop",
    "AgentLoopError",
    "AssistantTurn",
    "ConversationState",
    "FinalReport",
    "GateResult",
    "LoopResult",
    "Message",
    "TextProtocolProvider",
    "ToolCall",
    "check_completion",
    "ensure_conversing",
    "environment_block",
    "initial_message",
    "parse_final_report",
    "parse_turn",
]
