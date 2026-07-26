"""Conversation state with bounded growth.

The opening message (task, instructions, environment, repo map) is stable and
must survive the whole run; tool traffic is dynamic and can be compacted once it
grows past the budget. Compaction summarises the oldest tool exchanges instead
of dropping them silently, so the model keeps knowing what it already tried.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .types import Message

#: Rough character budget before compaction kicks in (~180k tokens).
DEFAULT_COMPACT_THRESHOLD = 720_000
#: How many of the most recent messages compaction always keeps verbatim.
KEEP_RECENT = 12


@dataclass
class ConversationState:
    """Ordered messages plus the compaction policy."""

    messages: list[Message] = field(default_factory=list)
    compact_threshold: int = DEFAULT_COMPACT_THRESHOLD
    keep_recent: int = KEEP_RECENT
    compactions: int = 0

    def add(self, message: Message) -> None:
        self.messages.append(message)

    def extend(self, messages: list[Message]) -> None:
        self.messages.extend(messages)

    def size(self) -> int:
        return sum(len(m.content) for m in self.messages)

    def approx_tokens(self) -> int:
        return sum(m.approx_tokens() for m in self.messages)

    def _summarise(self, messages: list[Message]) -> str:
        lines: list[str] = []
        for message in messages:
            if message.role == "assistant":
                for call in message.tool_calls:
                    lines.append(f"- called {call.describe()}")
                if message.content.strip() and not message.tool_calls:
                    lines.append(f"- said: {message.content.strip()[:200]}")
            elif message.role == "tool":
                first = (message.content.strip().splitlines() or [""])[0]
                status = "ERROR" if message.content.startswith("ERROR") else "ok"
                lines.append(f"  -> {message.name}: {status}: {first[:200]}")
        body = "\n".join(lines[-200:]) or "(no tool activity)"
        return (
            "<compacted_history>\n"
            "Earlier investigation, summarised to save context. Re-read files with "
            "read_file if you need their exact contents again.\n"
            f"{body}\n"
            "</compacted_history>"
        )

    def compact_if_needed(self) -> bool:
        """Collapse old tool traffic when the transcript outgrows the budget."""
        if self.size() <= self.compact_threshold or len(self.messages) <= self.keep_recent + 2:
            return False

        head = self.messages[:1]  # the stable opening message
        tail = self.messages[-self.keep_recent :]
        # Never start the tail with an orphaned tool result.
        while tail and tail[0].role == "tool":
            tail = tail[1:]
        middle = self.messages[1 : len(self.messages) - len(tail)]
        if not middle:
            return False

        self.messages = [
            *head,
            Message(role="user", content=self._summarise(middle)),
            *tail,
        ]
        self.compactions += 1
        return True
