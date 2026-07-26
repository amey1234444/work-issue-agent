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
    comments: list[str] = field(default_factory=list)

    def as_prompt(self, max_comments: int = 6) -> str:
        labels = ", ".join(self.labels) if self.labels else "none"
        text = (
            f"Issue #{self.number}: {self.title}\n"
            f"URL: {self.url}\n"
            f"Labels: {labels}\n\n"
            f"{self.body or '(no description provided)'}"
        )
        if self.comments:
            # Older discussion is noise; the latest comments carry the decisions.
            recent = self.comments[-max_comments:]
            omitted = len(self.comments) - len(recent)
            header = f"\n\n## Latest comments ({omitted} older omitted)" if omitted else "\n\n## Comments"
            text += header + "\n" + "\n\n".join(recent)
        return text

    @property
    def acceptance_criteria(self) -> str:
        """Any explicit acceptance-criteria section of the issue body."""
        lowered = self.body.lower()
        for marker in ("acceptance criteria", "expected result", "definition of done"):
            index = lowered.find(marker)
            if index != -1:
                return self.body[index:][:2000].strip()
        return ""


@dataclass
class PullRequest:
    """A GitHub pull request, including its mergeability with the base branch."""

    owner: str
    repo: str
    number: int
    title: str = ""
    body: str = ""
    url: str = ""
    head_ref: str = ""
    base_ref: str = ""
    mergeable: bool | None = None
    mergeable_state: str = "unknown"
    draft: bool = False

    @property
    def has_conflicts(self) -> bool:
        return self.mergeable is False or self.mergeable_state == "dirty"


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
