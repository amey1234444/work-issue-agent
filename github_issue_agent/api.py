"""Programmatic (library) API for the work-issue-agent.

This is the importable counterpart to the CLI. :func:`run_workflow` (and the
:func:`work_issue` convenience wrapper) take plain keyword arguments, drive the
plan -> implement -> validate -> publish pipeline, and return a structured
:class:`WorkflowResult`. Hard failures raise :class:`AgentError`, which carries
a stable ``code`` / ``exit_code`` and a ``recovery`` hint.

Guarantees:

* The developer's checkout is never edited directly: git repositories get a
  disposable worktree under ``.agent_work/<run_id>`` on a private branch.
* Only the files the agent itself changed are staged and committed.
* A PR is only opened when every repository-required check passed on the exact
  tree being published (``validation.status == "passed"``). Failed, skipped,
  blocked, stale or missing validation fails closed.
* Provider API keys are run-scoped; the GitHub token is only ever handed to
  the single ``git push`` process and never written to ``.git/config``.

Example::

    from work_issue_agent import work_issue

    result = work_issue(
        "https://github.com/org/repo/issues/123",
        provider="openrouter",
        api_key="sk-or-...",
        repo_path=".",
        github_token="ghp_...",
    )
    print(result.pr_url, result.validation.status)
"""

from __future__ import annotations

import glob
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import git_ops
from .config import Config, ConfigError
from .context import build_repo_context
from .editor import EditError, FileChange, apply_edits, merge_changes
from .errors import AgentError, CancelledError
from .github_client import GitHubClient, GitHubError
from .llm import LLMError, get_provider
from .models import Implementation, Issue
from .paths import PathPolicy, PathPolicyError
from .runner import CancellationToken, Deadline
from .validation import (
    CheckStatus,
    ValidationReport,
    compute_tree_hash,
    plan_checks,
    run_validation,
    skipped_report,
)
from .workflow import Agent, ModelOutputError, build_task
from .workspace import Workspace, create_workspace

# Progress event callback: (kind, message). ``kind`` is a short tag such as
# "issue", "context", "plan", "implement", "tests", "pr", "workspace".
EventHandler = Callable[[str, str], None]


def new_run_id() -> str:
    return f"{time.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"


@dataclass
class WorkflowResult:
    """Structured outcome of a single workflow run."""

    workflow: str
    run_id: str = ""
    status: str = "not_run"
    """Terminal state: ``planned`` | ``validated`` | ``unvalidated`` | ``published``."""
    summary: str = ""
    plan: str = ""
    changes: list[FileChange] = field(default_factory=list)
    validation: ValidationReport = field(default_factory=ValidationReport)
    branch: str | None = None
    base: str | None = None
    commit: str | None = None
    pr_url: str | None = None
    issue_number: int | None = None
    dry_run: bool = False
    workspace: str | None = None
    """Path of the (kept) worktree containing the changes, when not published."""

    @property
    def changed_files(self) -> list[str]:
        return [c.path for c in self.changes]

    @property
    def tests_passed(self) -> bool:
        """``True`` only when validation is authoritative and passed."""
        return self.validation.status == CheckStatus.PASSED

    @property
    def test_output(self) -> str:
        return self.validation.output

    def as_dict(self) -> dict[str, object]:
        return {
            "workflow": self.workflow,
            "run_id": self.run_id,
            "status": self.status,
            "summary": self.summary,
            "plan": self.plan,
            "changes": [
                {"path": c.path, "action": c.action, "old_hash": c.old_hash, "new_hash": c.new_hash}
                for c in self.changes
            ],
            "validation": self.validation.as_dict(),
            "branch": self.branch,
            "base": self.base,
            "commit": self.commit,
            "pr_url": self.pr_url,
            "issue_number": self.issue_number,
            "dry_run": self.dry_run,
            "workspace": self.workspace,
        }


def discover_workflows(repo_path: Path) -> dict[str, Path]:
    """Return ``{name: path}`` for every ``.ai/workflows/<name>.md`` in the repo."""
    found: dict[str, Path] = {}
    for path in sorted(glob.glob(str(repo_path / ".ai" / "workflows" / "*.md"))):
        p = Path(path)
        found[p.stem] = p
    return found


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
        config.api_key = api_key
    try:
        config.validate()
    except ConfigError as exc:
        raise AgentError(str(exc), code="configuration", phase="config") from exc


# -- checkpoints -----------------------------------------------------------------
def _state_file(origin: Path, run_id: str) -> Path:
    return origin / ".agent_work" / f"{run_id}.json"


def _checkpoint(origin: Path, result: WorkflowResult, phase: str) -> None:
    try:
        path = _state_file(origin, result.run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = result.as_dict()
        data["phase"] = phase
        data["updated_at"] = time.time()
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def _guard(cancel: CancellationToken | None, deadline: Deadline, phase: str) -> None:
    if cancel is not None and cancel.cancelled:
        raise CancelledError(phase=phase)
    if deadline.expired:
        raise AgentError(
            f"Run deadline of {int(deadline.seconds)}s exceeded during {phase}.",
            code="budget",
            phase=phase,
            recovery="Increase deadline_seconds in .ai/config.yaml or narrow the task.",
        )


def _check_repo_identity(issue: Issue, origin_url: str | None, *, allow_mismatch: bool) -> None:
    if not origin_url:
        return
    try:
        owner, repo = GitHubClient.parse_repo_url(origin_url)
    except GitHubError:
        return
    if (owner.lower(), repo.lower()) != (issue.owner.lower(), issue.repo.lower()) and not allow_mismatch:
        raise AgentError(
            f"Issue belongs to {issue.owner}/{issue.repo} but the checkout's origin is {owner}/{repo}.",
            code="configuration",
            phase="issue",
            recovery="Run inside a checkout of the issue's repository, or pass allow_repo_mismatch=True.",
        )


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
    isolate: bool = True,
    allow_unvalidated: bool = False,
    allow_repo_mismatch: bool = False,
    run_id: str | None = None,
    cancel: CancellationToken | None = None,
    on_event: EventHandler | None = None,
) -> WorkflowResult:
    """Run a named workflow end-to-end and return a :class:`WorkflowResult`.

    Parameters mirror the CLI flags. ``api_key`` and ``github_token``, when
    given, take precedence over environment variables / ``.env`` files and are
    never written back into the process environment. Either ``issue_url`` or
    ``prompt`` must be provided.
    """

    def emit(kind: str, message: str) -> None:
        if on_event is not None:
            on_event(kind, message)

    run_id = run_id or new_run_id()
    origin_path = Path(repo_path).resolve()
    if not origin_path.is_dir():
        raise AgentError(f"Repository path does not exist: {origin_path}", code="configuration", phase="config")
    try:
        config = Config.load(origin_path)
    except ConfigError as exc:
        raise AgentError(str(exc), code="configuration", phase="config") from exc
    _apply_overrides(
        config,
        provider=provider,
        model=model,
        api_key=api_key,
        github_token=github_token,
        max_iterations=max_iterations,
    )
    deadline = Deadline(config.deadline_seconds)

    workflows = discover_workflows(origin_path)
    if workflow not in workflows:
        available = ", ".join(workflows) or "(none)"
        raise AgentError(
            f"Unknown workflow {workflow!r}. Available: {available}",
            code="configuration",
            phase="config",
            recovery="Add .ai/workflows/<name>.md or run `ai-agent init`.",
        )
    workflow_text = workflows[workflow].read_text(encoding="utf-8")

    gh: GitHubClient | None = None
    if issue_url or (open_pr and not dry_run):
        try:
            gh = GitHubClient(config.github_token)
        except GitHubError as exc:
            raise AgentError(str(exc), code="authentication", phase="github") from exc

    origin_url = git_ops.remote_url(origin_path) if git_ops.is_git_repo(origin_path) else None

    issue = None
    if issue_url and gh is not None:
        try:
            issue = gh.get_issue(issue_url)
        except GitHubError as exc:
            raise AgentError(str(exc), code="authentication", phase="issue") from exc
        _check_repo_identity(issue, origin_url, allow_mismatch=allow_repo_mismatch)
        emit("issue", f"Fetched issue #{issue.number}: {issue.title}")

    try:
        task = build_task(issue, prompt)
    except ValueError as exc:
        raise AgentError(str(exc), code="configuration", phase="task") from exc

    try:
        provider_impl = get_provider(config)
    except LLMError as exc:
        raise AgentError(str(exc), code="authentication", phase="provider") from exc

    result = WorkflowResult(
        workflow=workflow,
        run_id=run_id,
        dry_run=dry_run,
        issue_number=issue.number if issue else None,
    )

    ws: Workspace = create_workspace(origin_path, run_id, isolate=isolate)
    if ws.isolated:
        emit("workspace", f"Isolated worktree {ws.path} on {ws.branch}")
    result.workspace = str(ws.path)
    policy = PathPolicy(ws.path, tuple(config.protected_paths))

    keep_workspace = False
    try:
        ctx = build_repo_context(ws.path, config, policy)
        emit("context", f"Loaded {len(ctx.instructions)} instruction file(s), {len(ctx.rules)} rule(s).")
        agent = Agent(provider_impl, config, ws.path, policy)

        _guard(cancel, deadline, "plan")
        try:
            plan = agent.plan(workflow_text, ctx, task)
        except (ModelOutputError, LLMError) as exc:
            raise AgentError(f"Planning failed: {exc}", code="provider", phase="plan", retryable=True) from exc
        result.plan = plan.as_text()
        emit("plan", result.plan)
        result.status = "planned"
        _checkpoint(ws.origin, result, "planned")

        if dry_run:
            planned = plan_checks(config.required_checks, [])
            result.validation = skipped_report(planned, compute_tree_hash(ws.path))
            result.workspace = None
            return result

        feedback: str | None = None
        impl: Implementation | None = None
        for attempt in range(1, config.max_iterations + 1):
            _guard(cancel, deadline, "implement")
            emit("implement", f"attempt {attempt}/{config.max_iterations}")
            try:
                impl = agent.implement(workflow_text, ctx, task, plan, feedback=feedback)
            except (ModelOutputError, LLMError) as exc:
                feedback = f"Your previous reply was rejected: {exc}. Reply with valid JSON only."
                emit("implement", f"Model output rejected: {exc}")
                continue
            try:
                latest = apply_edits(ws.path, impl.edits, policy=policy)
            except (EditError, PathPolicyError) as exc:
                feedback = f"Your edits were rejected and rolled back: {exc}"
                emit("implement", f"Edits rejected: {exc}")
                continue
            result.changes = merge_changes(result.changes, latest)
            result.validation.mark_stale_if_changed(compute_tree_hash(ws.path))
            emit("implement", "Changes: " + (", ".join(c.describe() for c in latest) or "(none)"))
            _checkpoint(ws.origin, result, "implemented")

            planned = plan_checks(config.required_checks, impl.commands)
            if not planned:
                result.validation = ValidationReport(tree_hash=compute_tree_hash(ws.path))
                emit("tests", "No checks configured; validation status: not_run.")
                break
            _guard(cancel, deadline, "validate")
            result.validation = run_validation(
                ws.path,
                planned,
                timeout=config.command_timeout,
                max_output_chars=config.max_output_chars,
                cancel=cancel,
                deadline=deadline,
                on_start=lambda cmd: emit("tests", f"$ {cmd}"),
            )
            _checkpoint(ws.origin, result, "validated")
            status = result.validation.status
            if status == CheckStatus.PASSED:
                emit("tests", "All checks passed.")
                break
            if status == CheckStatus.BLOCKED:
                _guard(cancel, deadline, "validate")
                emit("tests", "Checks could not run (blocked); not retrying.")
                break
            emit("tests", f"Checks {status.value}; asking the model to fix.")
            feedback = result.validation.output[-6000:]

        if impl is None:
            raise AgentError(
                "No valid implementation was produced.",
                code="provider",
                phase="implement",
                retryable=True,
                recovery="Retry, increase max_iterations, or try a stronger model.",
            )
        result.summary = impl.summary

        # Evidence must describe the exact tree we are about to publish.
        result.validation.mark_stale_if_changed(compute_tree_hash(ws.path))
        result.status = "validated" if result.validation.passed else "unvalidated"

        if not result.changes:
            raise AgentError(
                "The model produced no file changes.",
                code="validation",
                phase="implement",
                retryable=True,
            )

        if not open_pr:
            keep_workspace = ws.isolated
            emit(
                "workspace",
                f"Changes left in {ws.path}" + (f" on branch {ws.branch}" if ws.branch else ""),
            )
            _checkpoint(ws.origin, result, "kept")
            return result

        if config.require_validation and not allow_unvalidated and not result.validation.passed:
            keep_workspace = ws.isolated
            _checkpoint(ws.origin, result, "blocked")
            status_name = result.validation.status.value
            hint = (
                "Configure test_command/checks in .ai/config.yaml so validation can run."
                if result.validation.status == CheckStatus.NOT_RUN
                else "Inspect the kept workspace, fix the failures, or rerun."
            )
            raise AgentError(
                f"Refusing to open a PR: validation status is {status_name!r}. Workspace kept at {ws.path}.",
                code="validation",
                phase="publish",
                recovery=f"{hint} Use allow_unvalidated=True to publish anyway (not recommended).",
            )

        assert gh is not None
        _guard(cancel, deadline, "publish")
        _publish(gh, config, ws, impl, result, base=base, origin_url=origin_url, emit=emit)
        return result
    except AgentError:
        keep_workspace = ws.isolated and bool(result.changes)
        if keep_workspace:
            result.workspace = str(ws.path)
        raise
    finally:
        if not keep_workspace:
            ws.cleanup(keep_branch=result.pr_url is not None)
            if result.workspace == str(ws.path) and ws.isolated:
                result.workspace = None


def _publish(
    gh: GitHubClient,
    config: Config,
    ws: Workspace,
    impl: Implementation,
    result: WorkflowResult,
    *,
    base: str | None,
    origin_url: str | None,
    emit: EventHandler,
) -> None:
    if not origin_url:
        raise AgentError(
            "Target repo has no 'origin' remote; cannot open a PR.",
            code="publication",
            phase="publish",
            recovery="Add an origin remote pointing at GitHub, or rerun with open_pr=False.",
        )
    try:
        owner, repo = gh.parse_repo_url(origin_url)
        base_branch = base or gh.default_branch(owner, repo)
    except GitHubError as exc:
        raise AgentError(str(exc), code="publication", phase="publish") from exc
    result.base = base_branch

    branch = git_ops.pick_branch_name(
        ws.origin,
        impl.branch,
        protected=config.protected_branches,
        base=base_branch,
        run_id=result.run_id,
    )
    if branch in config.protected_branches or branch == base_branch:
        raise AgentError(f"Refusing to publish to protected branch {branch!r}.", code="publication", phase="publish")

    try:
        if ws.isolated:
            git_ops.rename_current_branch(ws.path, branch)
            ws.branch = branch
        else:
            if git_ops.branch_exists(ws.path, branch):
                raise AgentError(f"Branch {branch!r} already exists.", code="conflict", phase="publish")
            git_ops.create_branch(ws.path, branch)

        manifest = [c.path for c in result.changes]
        git_ops.stage_paths(ws.path, manifest)
        staged = set(git_ops.staged_paths(ws.path))
        extra = staged - set(manifest)
        if extra:
            raise AgentError(
                f"Staging included files outside the change manifest: {sorted(extra)}",
                code="internal",
                phase="publish",
            )
        if not staged:
            raise AgentError("No file changes to commit; aborting PR.", code="validation", phase="publish")
        result.commit = git_ops.commit(ws.path, impl.commit_message)
        result.branch = branch
        _checkpoint(ws.origin, result, "committed")

        assert config.github_token is not None
        remote_sha = git_ops.remote_branch_sha(ws.path, branch, token=config.github_token)
        if remote_sha is None:
            git_ops.push(ws.path, branch, token=config.github_token)
        elif remote_sha != result.commit:
            raise AgentError(
                f"Remote branch {branch!r} already exists with different history.",
                code="conflict",
                phase="publish",
                recovery="Delete or rename the remote branch and rerun.",
            )
        _checkpoint(ws.origin, result, "pushed")
    except git_ops.GitError as exc:
        raise AgentError(str(exc), code="publication", phase="publish", retryable=True) from exc

    body = impl.pr_body.rstrip() + "\n\n---\n" + result.validation.evidence_markdown()
    if result.issue_number:
        body += f"\n\nResolves #{result.issue_number}"
    try:
        result.pr_url = gh.create_pull_request(
            owner=owner,
            repo=repo,
            title=impl.pr_title,
            head=branch,
            base=base_branch,
            body=body,
            draft=config.draft_pr,
        )
    except GitHubError as exc:
        raise AgentError(
            f"{exc} (branch {branch!r} was pushed; rerun to reconcile).",
            code="publication",
            phase="publish",
            retryable=True,
        ) from exc
    result.status = "published"
    _checkpoint(ws.origin, result, "published")
    emit("pr", f"Opened PR: {result.pr_url}")


def work_issue(issue_url: str, **kwargs: object) -> WorkflowResult:
    """Resolve a GitHub issue with the ``work-issue`` workflow.

    Convenience wrapper around :func:`run_workflow` with
    ``workflow="work-issue"``. Accepts the same keyword arguments (``provider``,
    ``api_key``, ``model``, ``repo_path``, ``github_token``, ``open_pr``,
    ``dry_run`` ...).
    """
    return run_workflow("work-issue", issue_url=issue_url, **kwargs)  # type: ignore[arg-type]


__all__ = [
    "AgentError",
    "EventHandler",
    "WorkflowResult",
    "discover_workflows",
    "new_run_id",
    "run_workflow",
    "work_issue",
]
