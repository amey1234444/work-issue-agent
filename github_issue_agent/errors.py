"""Typed, categorised errors shared by the API and the CLI.

Every failure the agent raises carries a stable ``code`` (a category a caller can
branch on), the ``phase`` in which it happened and whether a retry is likely to
help. The CLI maps ``code`` to a process exit code.
"""

from __future__ import annotations

from typing import Literal

ErrorCode = Literal[
    "configuration",
    "authentication",
    "provider",
    "validation",
    "workspace",
    "conflict",
    "publication",
    "cancelled",
    "budget",
    "internal",
]

EXIT_CODES: dict[str, int] = {
    "ok": 0,
    "validation": 1,
    "configuration": 2,
    "authentication": 3,
    "provider": 4,
    "workspace": 5,
    "conflict": 5,
    "publication": 6,
    "cancelled": 7,
    "budget": 8,
    "internal": 9,
}


class AgentError(RuntimeError):
    """Raised for any unrecoverable error during a workflow run."""

    def __init__(
        self,
        message: str,
        *,
        code: ErrorCode = "internal",
        phase: str = "",
        retryable: bool = False,
        recovery: str = "",
    ) -> None:
        super().__init__(message)
        self.code: ErrorCode = code
        self.phase = phase
        self.retryable = retryable
        self.recovery = recovery

    @property
    def exit_code(self) -> int:
        return EXIT_CODES.get(self.code, EXIT_CODES["internal"])

    def as_dict(self) -> dict[str, object]:
        return {
            "error": str(self),
            "code": self.code,
            "exit_code": self.exit_code,
            "phase": self.phase,
            "retryable": self.retryable,
            "recovery": self.recovery,
        }


class CancelledError(AgentError):
    def __init__(self, message: str = "Run was cancelled.", *, phase: str = "") -> None:
        super().__init__(message, code="cancelled", phase=phase)
