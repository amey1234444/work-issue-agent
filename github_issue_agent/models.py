"""Typed data structures exchanged between the CLI, the LLM and the executor."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

EditAction = Literal["create", "modify", "delete"]


@dataclass
class Issue:
    """A GitHub issue the agent is asked to resolve."""

    owner: str
    repo: str
    number: int
    title: str
    body: str
    url: str
    labels: list[str] = field(default_factory=list)

    def as_prompt(self) -> str:
        labels = ", ".join(self.labels) if self.labels else "none"
        return (
            f"Issue #{self.number}: {self.title}\n"
            f"URL: {self.url}\n"
            f"Labels: {labels}\n\n"
            f"{self.body or '(no description provided)'}"
        )


@dataclass
class Plan:
    """Output of the planning step."""

    understanding: str
    files_to_read: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)

    def as_text(self) -> str:
        steps = "\n".join(f"  {i + 1}. {s}" for i, s in enumerate(self.steps))
        files = "\n".join(f"  - {f}" for f in self.files_to_read) or "  (none)"
        return f"Understanding:\n  {self.understanding}\n\nFiles to read:\n{files}\n\nPlan:\n{steps}"


@dataclass
class FileEdit:
    """A single change to a file in the target repository."""

    path: str
    action: EditAction
    content: str = ""


@dataclass
class Implementation:
    """Output of the coding step: the concrete changes plus PR metadata."""

    summary: str
    branch: str
    commit_message: str
    pr_title: str
    pr_body: str
    edits: list[FileEdit] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
