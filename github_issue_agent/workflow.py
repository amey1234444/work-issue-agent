"""The orchestration engine: turn a workflow + context into edits, tests and a PR."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .context import RepoContext, read_files
from .llm import LLMProvider
from .models import FileEdit, Implementation, Issue, Plan

# ---------------------------------------------------------------------------
# Prompt templates. Repos can override these by adding .ai/prompts/<name>.md.
# ---------------------------------------------------------------------------

DEFAULT_PLANNER_PROMPT = """You are the PLANNING agent in a workflow-driven coding system.
You are given the repository's own instruction files, its file tree, the workflow
to follow, and the task. Decide what needs to happen.

Respond with ONLY a JSON object of this exact shape (no prose, no code fences):
{
  "understanding": "one paragraph restating the task in your own words",
  "files_to_read": ["relative/path/one.py", "relative/path/two.py"],
  "steps": ["short imperative step", "..."]
}
Pick files_to_read conservatively: only files you must see to implement the change."""

DEFAULT_CODER_PROMPT = """You are the CODING agent in a workflow-driven coding system.
Implement the task by emitting concrete file edits. Honour every rule in the
repository instruction files (style, testing, language version, etc.).

For 'create' and 'modify' actions you MUST return the COMPLETE new file content,
not a diff. Keep changes minimal and focused on the task.

Respond with ONLY a JSON object of this exact shape (no prose, no code fences):
{
  "summary": "what you changed and why",
  "branch": "short-kebab-branch-name",
  "commit_message": "conventional-commit style message",
  "pr_title": "concise PR title",
  "pr_body": "markdown PR description",
  "edits": [
    {"path": "relative/path", "action": "create|modify|delete", "content": "full file content"}
  ],
  "commands": ["test or lint command to run, e.g. pytest -q"]
}"""


@dataclass
class WorkflowResult:
    implementation: Implementation
    changed: list[str]
    test_output: str
    tests_passed: bool


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of an LLM response, tolerating code fences."""
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1)
    start = cleaned.find("{")
    if start == -1:
        raise ValueError(f"No JSON object found in model output:\n{text[:500]}")
    depth = 0
    for i in range(start, len(cleaned)):
        ch = cleaned[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(cleaned[start : i + 1])
    raise ValueError(f"Unbalanced JSON braces in model output:\n{text[:500]}")


class Agent:
    """Coordinates the planning -> coding -> test -> (retry) loop."""

    def __init__(self, provider: LLMProvider, config: Config, repo_path: Path):
        self.provider = provider
        self.config = config
        self.repo_path = repo_path

    def _load_prompt(self, name: str, default: str) -> str:
        override = self.repo_path / ".ai" / "prompts" / f"{name}.md"
        if override.is_file():
            return override.read_text(encoding="utf-8")
        return default

    def plan(self, workflow_text: str, ctx: RepoContext, task: str) -> Plan:
        system = self._load_prompt("planner", DEFAULT_PLANNER_PROMPT)
        user = (
            f"# Workflow to follow\n{workflow_text}\n\n"
            f"# Repository instructions\n{ctx.instructions_block()}\n\n"
            f"# Repository file tree\n{ctx.tree}\n\n"
            f"# Task\n{task}\n"
        )
        raw = self.provider.complete(system, user)
        data = extract_json(raw)
        return Plan(
            understanding=str(data.get("understanding", "")),
            files_to_read=[str(p) for p in data.get("files_to_read", [])],
            steps=[str(s) for s in data.get("steps", [])],
        )

    def implement(
        self,
        workflow_text: str,
        ctx: RepoContext,
        task: str,
        plan: Plan,
        feedback: str | None = None,
    ) -> Implementation:
        system = self._load_prompt("coder", DEFAULT_CODER_PROMPT)
        file_blobs = read_files(self.repo_path, plan.files_to_read)
        files_section = "\n\n".join(
            f"----- {name} -----\n{body}" for name, body in file_blobs.items()
        ) or "(no files were pre-loaded)"

        user = (
            f"# Workflow to follow\n{workflow_text}\n\n"
            f"# Repository instructions\n{ctx.instructions_block()}\n\n"
            f"# Plan\n{plan.as_text()}\n\n"
            f"# Relevant files\n{files_section}\n\n"
            f"# Task\n{task}\n"
        )
        if feedback:
            user += (
                "\n# Previous attempt failed its tests. Fix the issues.\n"
                f"{feedback}\n"
            )
        raw = self.provider.complete(system, user)
        data = extract_json(raw)
        edits = [
            FileEdit(
                path=str(e["path"]),
                action=str(e.get("action", "modify")),  # type: ignore[arg-type]
                content=str(e.get("content", "")),
            )
            for e in data.get("edits", [])
        ]
        return Implementation(
            summary=str(data.get("summary", "")),
            branch=str(data.get("branch", "agent/change")),
            commit_message=str(data.get("commit_message", "agent: apply changes")),
            pr_title=str(data.get("pr_title", "Changes by work-issue-agent")),
            pr_body=str(data.get("pr_body", "")),
            edits=edits,
            commands=[str(c) for c in data.get("commands", [])],
        )


def build_task(issue: Issue | None, prompt: str | None) -> str:
    """Combine an issue and/or free-form prompt into a single task description."""
    parts: list[str] = []
    if issue is not None:
        parts.append(issue.as_prompt())
    if prompt:
        parts.append(prompt)
    if not parts:
        raise ValueError("A task requires an issue URL and/or a --prompt.")
    return "\n\n".join(parts)
