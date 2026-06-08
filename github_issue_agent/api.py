"""Programmatic (library) API for the work-issue-agent.

This is the importable counterpart to the CLI. Instead of parsing argv,
printing and returning process exit codes, :func:`run_workflow` (and the
:func:`work_issue` convenience wrapper) take plain keyword arguments, drive the
same plan -> implement -> test -> PR pipeline, and return a structured
:class:`WorkflowResult`. Hard failures raise :class:`AgentError`.

Example::

    from work_issue_agent import work_issue

    result = work_issue(
        "https://github.com/org/repo/issues/123",
        provider="openrouter",
        api_key="sk-or-...",
        model="z-ai/glm-4.5-air:free",
        repo_path=".",
        github_token="ghp_...",
    )
    print(result.pr_url, result.tests_passed)
"""

from __future__ import annotations

import glob
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .context import build_repo_context
from .editor import apply_edits
from .git_ops import commit_all, create_branch, has_changes, push, set_remote
from .github_client import GitHubClient, GitHubError
from .llm import LLMError, get_provider
from .runner import run_all
from .workflow import Agent, build_task

# Maps a provider name to the environment variable its SDK reads the key from.
_PROVIDER_API_KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}

# Progress event callback: (kind, message). ``kind`` is a short tag such as
# "issue", "context", "plan", "implement", "tests", "pr".
EventHandler = Callable[[str, str], None]


class AgentError(RuntimeError):
    """Raised for any unrecoverable error during a workflow run."""


@dataclass
class WorkflowResult:
    """Structured outcome of a single workflow run."""

    workflow: str
    tests_passed: bool
    summary: str = ""
    plan: str = ""
    changed_files: list[str] = field(default_factory=list)
    test_output: str = ""
    branch: str | None = None
    pr_url: str | None = None
    issue_number: int | None = None
    dry_run: bool = False


def discover_workflows(repo_path: Path) -> dict[str, Path]:
    """Return ``{name: path}`` for every ``.ai/workflows/<name>.md`` in the repo."""
    found: dict[str, Path] = {}
    for path in sorted(glob.glob(str(repo_path / ".ai" / "workflows" / "*.md"))):
        p = Path(path)
        found[p.stem] = p
    return found


def authed_remote(url: str, token: str) -> str:
    """Inject a token into an https remote URL for push access."""
    if url.startswith("https://") and "@" not in url.split("//", 1)[1].split("/", 1)[0]:
        return url.replace("https://", f"https://x-access-token:{token}@", 1)
    return url


def _apply_overrides(
    config: Config,
    *,
    provider: str | None,
    model: str | None,
    api_key: str | None,
    github_token: str | None,
    max_iterations: int | None,
) -> None:
    if provider:
        config.provider = provider.lower()
    if model:
        if config.provider == "anthropic":
            config.anthropic_model = model
        elif config.provider == "openai":
            config.openai_model = model
        elif config.provider == "openrouter":
            config.openrouter_model = model
    if github_token:
        config.github_token = github_token
    if max_iterations is not None:
        config.max_iterations = max_iterations
    if api_key:
        env_var = _PROVIDER_API_KEY_ENV.get(config.provider)
        if env_var:
            os.environ[env_var] = api_key


def run_workflow(
    workflow: str = "work-issue",
    *,
    repo_path: str | Path = ".",
    issue_url: str | None = None,
    prompt: str | None = None,
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    github_token: str | None = None,
    base: str | None = None,
    max_iterations: int | None = None,
    open_pr: bool = True,
    dry_run: bool = False,
    on_event: EventHandler | None = None,
) -> WorkflowResult:
    """Run a named workflow end-to-end and return a :class:`WorkflowResult`.

    Parameters mirror the CLI flags. ``api_key`` and ``github_token``, when
    given, take precedence over environment variables / ``.env`` files. Either
    ``issue_url`` or ``prompt`` must be provided.
    """

    def emit(kind: str, message: str) -> None:
        if on_event is not None:
            on_event(kind, message)

    path = Path(repo_path).resolve()
    config = Config.load(path)
    _apply_overrides(
        config,
        provider=provider,
        model=model,
        api_key=api_key,
        github_token=github_token,
        max_iterations=max_iterations,
    )

    workflows = discover_workflows(path)
    if workflow not in workflows:
        available = ", ".join(workflows) or "(none)"
        raise AgentError(f"Unknown workflow {workflow!r}. Available: {available}")
    workflow_text = workflows[workflow].read_text(encoding="utf-8")

    gh: GitHubClient | None = None
    if issue_url or open_pr:
        try:
            gh = GitHubClient(config.github_token)
        except GitHubError as exc:
            raise AgentError(str(exc)) from exc

    issue = None
    if issue_url and gh is not None:
        issue = gh.get_issue(issue_url)
        emit("issue", f"Fetched issue #{issue.number}: {issue.title}")

    try:
        task = build_task(issue, prompt)
    except ValueError as exc:
        raise AgentError(str(exc)) from exc

    ctx = build_repo_context(path, config)
    emit(
        "context",
        f"Loaded {len(ctx.instructions)} instruction file(s), {len(ctx.rules)} rule(s).",
    )

    try:
        provider_impl = get_provider(config)
    except LLMError as exc:
        raise AgentError(str(exc)) from exc

    agent = Agent(provider_impl, config, path)

    plan = agent.plan(workflow_text, ctx, task)
    emit("plan", plan.as_text())

    result = WorkflowResult(
        workflow=workflow,
        tests_passed=True,
        plan=plan.as_text(),
        dry_run=dry_run,
        issue_number=issue.number if issue else None,
    )
    if dry_run:
        return result

    feedback: str | None = None
    impl = None
    for attempt in range(1, config.max_iterations + 1):
        emit("implement", f"attempt {attempt}/{config.max_iterations}")
        impl = agent.implement(workflow_text, ctx, task, plan, feedback=feedback)
        result.changed_files = apply_edits(path, impl.edits)
        emit("implement", "Changes: " + (", ".join(result.changed_files) or "(none)"))

        commands = impl.commands or ([config.test_command] if config.test_command else [])
        if not commands:
            result.tests_passed = True
            emit("tests", "No test command specified; skipping test run.")
            break
        results = run_all(path, commands)
        result.test_output = "\n\n".join(f"$ {r.command}\n{r.output}" for r in results)
        result.tests_passed = all(r.ok for r in results)
        if result.tests_passed:
            emit("tests", "Tests passed.")
            break
        emit("tests", "Tests failed; will ask the model to fix.")
        feedback = result.test_output[-6000:]

    if impl is None:
        raise AgentError("No implementation was produced.")

    result.summary = impl.summary
    result.branch = impl.branch

    if not open_pr:
        return result

    if not has_changes(path):
        raise AgentError("No file changes to commit; aborting PR.")

    assert gh is not None
    origin = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=path,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if not origin:
        raise AgentError("Target repo has no 'origin' remote; cannot open a PR.")
    owner, repo = gh.parse_repo_url(origin)
    base_branch = base or gh.default_branch(owner, repo)

    create_branch(path, impl.branch)
    commit_all(path, impl.commit_message)
    assert config.github_token is not None
    set_remote(path, authed_remote(origin, config.github_token))
    push(path, impl.branch)

    result.pr_url = gh.create_pull_request(
        owner=owner,
        repo=repo,
        title=impl.pr_title,
        head=impl.branch,
        base=base_branch,
        body=impl.pr_body,
    )
    emit("pr", f"Opened PR: {result.pr_url}")
    return result


def work_issue(issue_url: str, **kwargs: object) -> WorkflowResult:
    """Resolve a GitHub issue with the ``work-issue`` workflow.

    Convenience wrapper around :func:`run_workflow` with
    ``workflow="work-issue"``. Accepts the same keyword arguments (``provider``,
    ``api_key``, ``model``, ``repo_path``, ``github_token``, ``open_pr``,
    ``dry_run`` ...).
    """
    return run_workflow("work-issue", issue_url=issue_url, **kwargs)  # type: ignore[arg-type]
