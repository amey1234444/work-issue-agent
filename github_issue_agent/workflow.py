"""The orchestration engine: turn a workflow + context into edits, tests and a PR."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .config import Config
from .context import RepoContext, read_files
from .llm import LLMProvider
from .models import FileEdit, Implementation, Issue, Plan
from .paths import PathPolicy

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
not a diff. Keep changes minimal and focused on the task. Use 'create' only for
files that do not exist yet and 'modify'/'delete' only for files that do.

The repository's configured checks always run; list any ADDITIONAL targeted
commands (e.g. a single test file) in "commands".

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


_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


class ModelOutputError(ValueError):
    """The model's reply could not be parsed or failed schema validation."""


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of an LLM response using a real decoder.

    Code fences are tolerated. Braces inside quoted strings are handled
    correctly because :meth:`json.JSONDecoder.raw_decode` is used rather than
    brace counting. Raises :class:`ModelOutputError` when no object is found.
    """
    if not text or not text.strip():
        raise ModelOutputError("Model returned empty output.")
    cleaned = text.strip()
    fence = _FENCE_RE.search(cleaned)
    if fence:
        cleaned = fence.group(1)
    decoder = json.JSONDecoder()
    pos = cleaned.find("{")
    while pos != -1:
        try:
            obj, _ = decoder.raw_decode(cleaned, pos)
        except json.JSONDecodeError:
            pos = cleaned.find("{", pos + 1)
            continue
        if isinstance(obj, dict):
            return obj
        pos = cleaned.find("{", pos + 1)
    raise ModelOutputError(f"No valid JSON object found in model output:\n{text[:500]}")


_EDIT_ACTIONS = {"create", "modify", "delete"}


def _expect_str_list(data: dict, key: str) -> list[str]:
    value = data.get(key, [])
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ModelOutputError(f"Field {key!r} must be a list of strings.")
    return value


def parse_plan(data: dict) -> Plan:
    understanding = data.get("understanding", "")
    if not isinstance(understanding, str):
        raise ModelOutputError("Field 'understanding' must be a string.")
    return Plan(
        understanding=understanding,
        files_to_read=_expect_str_list(data, "files_to_read"),
        steps=_expect_str_list(data, "steps"),
    )


def parse_implementation(data: dict) -> Implementation:
    raw_edits = data.get("edits", [])
    if raw_edits is None:
        raw_edits = []
    if not isinstance(raw_edits, list):
        raise ModelOutputError("Field 'edits' must be a list.")
    edits: list[FileEdit] = []
    for i, e in enumerate(raw_edits):
        if not isinstance(e, dict) or not isinstance(e.get("path"), str) or not e["path"]:
            raise ModelOutputError(f"edits[{i}] must be an object with a non-empty 'path'.")
        action = e.get("action", "modify")
        if action not in _EDIT_ACTIONS:
            raise ModelOutputError(
                f"edits[{i}].action must be one of {sorted(_EDIT_ACTIONS)}, got {action!r}."
            )
        content = e.get("content", "")
        if content is None:
            content = ""
        if not isinstance(content, str):
            raise ModelOutputError(f"edits[{i}].content must be a string.")
        if action != "delete" and "content" not in e:
            raise ModelOutputError(f"edits[{i}] ({action}) is missing 'content'.")
        edits.append(FileEdit(path=e["path"], action=action, content=content))

    def _str(key: str, default: str) -> str:
        value = data.get(key, default)
        if value is None:
            return default
        if not isinstance(value, str):
            raise ModelOutputError(f"Field {key!r} must be a string.")
        return value or default

    return Implementation(
        summary=_str("summary", ""),
        branch=_str("branch", "agent/change"),
        commit_message=_str("commit_message", "agent: apply changes"),
        pr_title=_str("pr_title", "Changes by work-issue-agent"),
        pr_body=_str("pr_body", ""),
        edits=edits,
        commands=_expect_str_list(data, "commands"),
    )


class Agent:
    """Coordinates the planning -> coding -> test -> (retry) loop."""

    def __init__(
        self,
        provider: LLMProvider,
        config: Config,
        repo_path: Path,
        policy: PathPolicy | None = None,
    ):
        self.provider = provider
        self.config = config
        self.repo_path = repo_path
        self.policy = policy or PathPolicy(repo_path)

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
        return parse_plan(extract_json(raw))

    def implement(
        self,
        workflow_text: str,
        ctx: RepoContext,
        task: str,
        plan: Plan,
        feedback: str | None = None,
    ) -> Implementation:
        system = self._load_prompt("coder", DEFAULT_CODER_PROMPT)
        file_blobs = read_files(self.repo_path, plan.files_to_read, policy=self.policy)
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
                "\n# Previous attempt failed. Fix the issues below.\n"
                "Files you already created exist now: use 'modify' for them.\n"
                f"{feedback}\n"
            )
        raw = self.provider.complete(system, user)
        return parse_implementation(extract_json(raw))


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
