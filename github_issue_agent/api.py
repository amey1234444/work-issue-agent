"""Programmatic (library) API for the work-issue-agent.

This is the importable counterpart to the CLI. Instead of parsing argv,
printing and returning process exit codes, :func:`run_workflow` (and the
:func:`work_issue` convenience wrapper) take plain keyword arguments, drive the
plan/implement or Codex-style agent pipeline, and return a structured
:class:`WorkflowResult`. Hard failures raise :class:`AgentError`.

Two execution modes are available:

``agent`` (default)
    one continuous tool-calling conversation: the model searches, reads,
    patches, runs tests and reviews its own diff before finishing.
``workflow``
    the original single-shot plan -> implement -> test -> retry pipeline.

Merge conflicts with the base branch are detected and resolved automatically
before a PR is opened; :func:`resolve_conflicts` and
:func:`fix_pull_request_conflicts` expose that machinery on its own.

Example::

    from github_issue_agent import work_issue

    result = work_issue(
        "https://github.com/org/repo/issues/123",
        provider="openrouter",
        api_key="sk-or-...",
        repo_path=".",
        github_token="ghp_...",
    )
    print(result.pr_url, result.tests_passed)
"""

from __future__ import annotations

import glob
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import git_ops
from .agent import (
    CODING_AGENT_INSTRUCTIONS,
    AgentLoop,
    AgentLoopError,
    environment_block,
    initial_message,
)
from .config import Config
from .context import build_repo_context
from .editor import apply_edits
from .git_ops import GitError, commit_all, create_branch, has_changes, push_with_token
from .github_client import GitHubClient, GitHubError
from .llm import LLMError, get_provider
from .merge import ResolutionResult, detect_conflicts, sync_with_base
from .merge import resolve_conflicts as _resolve_conflicts
from .models import Issue
from .repo_map import build_repo_map
from .runner import run_all
from .tools import PlanBoard, default_registry
from .validation.anti_cheating import report as integrity_report
from .workflow import Agent, build_task

# Maps a provider name to the environment variable its SDK reads the key from.
_PROVIDER_API_KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}

# Progress event callback: (kind, message). ``kind`` is a short tag such as
# "issue", "context", "plan", "tool", "implement", "tests", "merge", "pr".
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
    mode: str = "workflow"
    tool_calls: list[str] = field(default_factory=list)
    integrity_warnings: list[str] = field(default_factory=list)
    conflicts: ResolutionResult | None = None


def discover_workflows(repo_path: Path) -> dict[str, Path]:
    """Return ``{name: path}`` for every ``.ai/workflows/<name>.md`` in the repo."""
    found: dict[str, Path] = {}
    for path in sorted(glob.glob(str(repo_path / ".ai" / "workflows" / "*.md"))):
        p = Path(path)
        found[p.stem] = p
    return found


def authed_remote(url: str, token: str) -> str:
    """Inject a token into an https remote URL for push access."""
    return git_ops.authed_url(url, token)


def _apply_overrides(
    config: Config,
    *,
    provider: str | None,
    model: str | None,
    api_key: str | None,
    github_token: str | None,
    max_iterations: int | None,
    mode: str | None = None,
    max_steps: int | None = None,
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
    if mode:
        config.mode = mode.lower()
    if max_steps is not None:
        config.max_steps = max_steps
    if api_key:
        env_var = _PROVIDER_API_KEY_ENV.get(config.provider)
        if env_var:
            os.environ[env_var] = api_key


def _safe_branch(repo_path: Path) -> str:
    """Current branch, or a placeholder outside a git checkout."""
    result = git_ops.git_raw(repo_path, "rev-parse", "--abbrev-ref", "HEAD")
    return result.stdout if result.ok else "(not a git checkout)"


def _default_validation_commands(config: Config, repo_path: Path) -> list[str]:
    if config.validation_commands:
        return list(config.validation_commands)
    if config.test_command:
        return [config.test_command]
    repo_map = build_repo_map(repo_path)
    commands: list[str] = []
    if "pytest" in repo_map.test_frameworks:
        commands.append("pytest -q")
    if "go test" in repo_map.test_frameworks:
        commands.append("go test ./...")
    if "cargo test" in repo_map.test_frameworks:
        commands.append("cargo test")
    return commands


def _sync_before_pr(
    *,
    repo_path: Path,
    base_branch: str,
    config: Config,
    provider_impl,
    emit: EventHandler,
) -> ResolutionResult | None:
    """Merge the base branch in, auto-resolving conflicts, before pushing."""
    if not config.auto_resolve_conflicts:
        return None
    remote_base = f"origin/{base_branch}"
    git_ops.fetch(repo_path, "origin", base_branch)
    if not git_ops.git_raw(repo_path, "rev-parse", "--verify", remote_base).ok:
        return None
    if not git_ops.would_conflict(repo_path, remote_base):
        merge = git_ops.merge(repo_path, remote_base)
        if merge.ok:
            return None
        git_ops.abort_merge(repo_path)
    emit("merge", f"Base branch {base_branch} conflicts with this change; resolving.")
    return sync_with_base(
        repo_path,
        remote_base,
        provider=provider_impl,
        prefer=config.conflict_preference,
        validation_commands=_default_validation_commands(config, repo_path),
        on_event=emit,
    )


def _run_agent_mode(
    *,
    repo_path: Path,
    config: Config,
    provider_impl,
    task: str,
    workflow_text: str,
    instructions_block: str,
    acceptance_criteria: str,
    base_branch: str,
    emit: EventHandler,
) -> tuple[WorkflowResult, object]:
    """Drive the Codex-style loop and translate its result for the harness."""
    repo_map = build_repo_map(repo_path)
    plan_board = PlanBoard()
    validation_commands = _default_validation_commands(config, repo_path)
    if validation_commands:
        workflow_text += "\n\n# Validation commands for this repository\n" + "\n".join(
            f"- {command}" for command in validation_commands
        )
    loop = AgentLoop(
        provider_impl,
        repo_path=repo_path,
        system_prompt=CODING_AGENT_INSTRUCTIONS + "\n\n# Workflow to follow\n" + workflow_text,
        registry=default_registry(plan_board),
        plan_board=plan_board,
        max_steps=config.max_steps,
        # Only demand test evidence when the repository actually has a suite.
        require_validation=bool(validation_commands),
        on_event=emit,
        extra_allowed_commands=config.allowed_commands,
    )
    message = initial_message(
        task=task,
        instructions_block=instructions_block,
        environment=environment_block(
            repo_path,
            branch=_safe_branch(repo_path),
            base_branch=base_branch,
            languages=repo_map.languages,
            test_frameworks=repo_map.test_frameworks,
        ),
        repository_map=repo_map.as_context_block(),
        acceptance_criteria=acceptance_criteria,
    )
    try:
        outcome = loop.run(message)
    except AgentLoopError as exc:
        raise AgentError(str(exc)) from exc

    warnings = list(outcome.gate.warnings) if outcome.gate else []
    if warnings:
        emit("integrity", integrity_report(outcome.diff))
    result = WorkflowResult(
        workflow="agent",
        mode="agent",
        tests_passed=outcome.validated,
        summary=outcome.report.summary,
        plan=plan_board.as_text(),
        changed_files=outcome.changed_files,
        test_output=outcome.report.validation,
        tool_calls=outcome.tool_calls,
        integrity_warnings=warnings,
    )
    return result, outcome.report


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
    mode: str | None = None,
    max_steps: int | None = None,
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
        mode=mode,
        max_steps=max_steps,
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

    issue: Issue | None = None
    if issue_url and gh is not None:
        try:
            issue = gh.get_issue(issue_url)
        except GitHubError as exc:
            raise AgentError(str(exc)) from exc
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

    origin = git_ops.remote_url(path)
    base_branch = base
    if base_branch is None and gh is not None and origin:
        try:
            owner, repo_name = gh.parse_repo_url(origin)
            base_branch = gh.default_branch(owner, repo_name)
        except GitHubError:
            base_branch = None
    base_branch = base_branch or "main"

    if config.mode == "agent":
        if dry_run:
            emit("plan", "[dry-run] Agent mode makes no edits until it is allowed to run.")
            return WorkflowResult(workflow=workflow, mode="agent", tests_passed=True, dry_run=True)
        result, report = _run_agent_mode(
            repo_path=path,
            config=config,
            provider_impl=provider_impl,
            task=task,
            workflow_text=workflow_text,
            instructions_block=ctx.instructions_block(),
            acceptance_criteria=issue.acceptance_criteria if issue else "",
            base_branch=base_branch,
            emit=emit,
        )
        result.workflow = workflow
        result.issue_number = issue.number if issue else None
        branch = report.branch  # type: ignore[attr-defined]
        commit_message = report.commit_message  # type: ignore[attr-defined]
        pr_title = report.pr_title  # type: ignore[attr-defined]
        pr_body = report.pr_body  # type: ignore[attr-defined]
    else:
        agent = Agent(provider_impl, config, path)
        plan = agent.plan(workflow_text, ctx, task)
        emit("plan", plan.as_text())
        result = WorkflowResult(
            workflow=workflow,
            mode="workflow",
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

            commands = impl.commands or _default_validation_commands(config, path)
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
        warnings = integrity_report(git_ops.diff(path, "HEAD"))
        if warnings:
            result.integrity_warnings = warnings.splitlines()
            emit("integrity", warnings)
        result.summary = impl.summary
        branch, commit_message = impl.branch, impl.commit_message
        pr_title, pr_body = impl.pr_title, impl.pr_body

    result.branch = branch

    if not open_pr:
        return result

    if not has_changes(path):
        raise AgentError("No file changes to commit; aborting PR.")
    if not origin:
        raise AgentError("Target repo has no 'origin' remote; cannot open a PR.")
    assert gh is not None
    owner, repo_name = gh.parse_repo_url(origin)

    try:
        create_branch(path, branch)
        commit_all(path, commit_message)
        result.conflicts = _sync_before_pr(
            repo_path=path,
            base_branch=base_branch,
            config=config,
            provider_impl=provider_impl,
            emit=emit,
        )
        if result.conflicts is not None and result.conflicts.unresolved_files:
            raise AgentError(
                "Could not automatically resolve conflicts with "
                f"{base_branch}: {', '.join(result.conflicts.unresolved_files)}"
            )
        assert config.github_token is not None
        push_with_token(path, branch, config.github_token)
    except GitError as exc:
        raise AgentError(str(exc)) from exc

    if result.conflicts is not None and result.conflicts.conflicted:
        pr_body += "\n\n### Merge conflicts resolved automatically\n" + "\n".join(
            f"- `{outcome.path}`: {', '.join(outcome.strategies) or outcome.note}"
            for outcome in result.conflicts.outcomes
        )
    if result.integrity_warnings:
        pr_body += "\n\n### Integrity warnings\n" + "\n".join(
            f"- {w}" for w in result.integrity_warnings
        )

    try:
        result.pr_url = gh.create_pull_request(
            owner=owner,
            repo=repo_name,
            title=pr_title,
            head=branch,
            base=base_branch,
            body=pr_body,
        )
    except GitHubError as exc:
        raise AgentError(str(exc)) from exc
    emit("pr", f"Opened PR: {result.pr_url}")
    return result


def work_issue(issue_url: str, **kwargs: object) -> WorkflowResult:
    """Resolve a GitHub issue with the ``work-issue`` workflow.

    Convenience wrapper around :func:`run_workflow` with
    ``workflow="work-issue"``. Accepts the same keyword arguments (``provider``,
    ``api_key``, ``model``, ``repo_path``, ``github_token``, ``open_pr``,
    ``dry_run``, ``mode`` ...).
    """
    return run_workflow("work-issue", issue_url=issue_url, **kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Merge-conflict entry points
# ---------------------------------------------------------------------------


def resolve_conflicts(
    *,
    repo_path: str | Path = ".",
    base: str | None = None,
    strategy: str = "merge",
    prefer: str | None = None,
    guidance: str = "",
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    use_llm: bool = True,
    commit: bool = True,
    push_branch: bool = False,
    on_event: EventHandler | None = None,
) -> ResolutionResult:
    """Resolve merge conflicts, either in progress or against ``base``.

    With no ``base``, the current (already conflicted) working tree is resolved
    in place. With ``base``, that ref is merged or rebased in first and the
    operation is rolled back if anything cannot be resolved safely.
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
        github_token=None,
        max_iterations=None,
    )
    if prefer:
        config.conflict_preference = prefer

    provider_impl = None
    if use_llm:
        try:
            provider_impl = get_provider(config)
        except LLMError as exc:
            emit("conflicts", f"Continuing with deterministic strategies only: {exc}")

    validation = _default_validation_commands(config, path)

    if base:
        ref = base
        if "/" not in ref:
            git_ops.fetch(path, "origin", ref)
            if git_ops.git_raw(path, "rev-parse", "--verify", f"origin/{ref}").ok:
                ref = f"origin/{ref}"
        return sync_with_base(
            path,
            ref,
            provider=provider_impl,
            strategy=strategy,
            prefer=config.conflict_preference,
            guidance=guidance,
            validation_commands=validation,
            on_event=emit,
        )

    result = _resolve_conflicts(
        path,
        provider=provider_impl,
        prefer=config.conflict_preference,
        guidance=guidance,
        validation_commands=validation,
        on_event=emit,
    )
    if commit and result.fully_resolved and git_ops.merge_in_progress(path):
        finish = git_ops.continue_merge(path, "merge: resolve conflicts automatically")
        result.committed = finish.ok
        emit("merge", "Merge committed." if finish.ok else f"Commit failed: {finish.stderr}")
    if push_branch and result.committed:
        token = config.github_token
        if not token:
            raise AgentError("Pushing requires GITHUB_TOKEN or GITHUB_PAT.")
        push_with_token(path, git_ops.current_branch(path), token)
        emit("merge", "Pushed the resolved branch.")
    return result


def fix_pull_request_conflicts(
    pr_url: str,
    *,
    repo_path: str | Path = ".",
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    github_token: str | None = None,
    prefer: str | None = None,
    guidance: str = "",
    push_branch: bool = True,
    comment: bool = False,
    on_event: EventHandler | None = None,
) -> ResolutionResult:
    """Bring a conflicted PR branch up to date with its base and push the fix."""

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
        max_iterations=None,
    )
    try:
        gh = GitHubClient(config.github_token)
        owner, repo_name, number = gh.parse_pr_url(pr_url)
        pull = gh.get_pull_request(owner, repo_name, number)
    except GitHubError as exc:
        raise AgentError(str(exc)) from exc

    emit(
        "pr",
        f"PR #{pull.number} ({pull.head_ref} -> {pull.base_ref}): "
        f"mergeable={pull.mergeable}, state={pull.mergeable_state}",
    )
    if git_ops.has_changes(path):
        raise AgentError("Working tree is dirty; commit or stash before fixing a PR.")

    git_ops.fetch(path, "origin", pull.head_ref)
    git_ops.fetch(path, "origin", pull.base_ref)
    try:
        git_ops.checkout(path, pull.head_ref)
    except GitError as exc:
        raise AgentError(f"Cannot check out {pull.head_ref}: {exc}") from exc
    git_ops.git_raw(path, "reset", "--hard", f"origin/{pull.head_ref}")

    if not pull.has_conflicts and not detect_conflicts(path):
        emit("pr", "GitHub reports no conflicts; nothing to do.")
        return ResolutionResult()

    result = resolve_conflicts(
        repo_path=path,
        base=f"origin/{pull.base_ref}",
        provider=provider,
        api_key=api_key,
        model=model,
        prefer=prefer,
        guidance=guidance,
        on_event=on_event,
    )
    if result.fully_resolved and result.committed and push_branch:
        assert config.github_token is not None
        push_with_token(path, pull.head_ref, config.github_token)
        emit("pr", f"Pushed the resolved {pull.head_ref} branch.")
        if comment:
            gh.comment(owner, repo_name, number, "Merge conflicts resolved automatically:\n\n" + result.report())
    return result
