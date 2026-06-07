"""Command-line entrypoint.

The available commands are *data*, not code: every ``.ai/workflows/<name>.md`` in
the target repo becomes a runnable command. ``work-issue`` is provided as sugar
for ``run work-issue --issue <url>``.
"""

from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

from . import __version__
from .config import Config
from .context import build_repo_context
from .git_ops import commit_all, create_branch, has_changes, push, set_remote
from .github_client import GitHubClient, GitHubError
from .llm import LLMError, get_provider
from .runner import run_all
from .workflow import Agent, build_task


def _eprint(msg: str) -> None:
    print(msg, file=sys.stderr)


def discover_workflows(repo_path: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for path in sorted(glob.glob(str(repo_path / ".ai" / "workflows" / "*.md"))):
        p = Path(path)
        found[p.stem] = p
    return found


def _authed_remote(url: str, token: str) -> str:
    if url.startswith("https://") and "@" not in url.split("//", 1)[1].split("/", 1)[0]:
        return url.replace("https://", f"https://x-access-token:{token}@", 1)
    return url


def cmd_list(args: argparse.Namespace) -> int:
    repo_path = Path(args.path).resolve()
    workflows = discover_workflows(repo_path)
    if not workflows:
        _eprint(f"No workflows found under {repo_path / '.ai' / 'workflows'}")
        return 1
    print("Available workflows:")
    for name, path in workflows.items():
        first_line = ""
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                first_line = line.lstrip("# ").strip()
                break
        print(f"  {name:<16} {first_line}")
    return 0


def _run_workflow(
    *,
    repo_path: Path,
    workflow_name: str,
    issue_url: str | None,
    prompt: str | None,
    base: str | None,
    dry_run: bool,
    make_pr: bool,
    provider_override: str | None,
) -> int:
    config = Config.load(repo_path)
    if provider_override:
        config.provider = provider_override.lower()

    workflows = discover_workflows(repo_path)
    if workflow_name not in workflows:
        _eprint(
            f"Unknown workflow {workflow_name!r}. Available: {', '.join(workflows) or '(none)'}"
        )
        return 1
    workflow_text = workflows[workflow_name].read_text(encoding="utf-8")

    issue = None
    gh: GitHubClient | None = None
    if issue_url or make_pr:
        try:
            gh = GitHubClient(config.github_token)
        except GitHubError as exc:
            _eprint(str(exc))
            return 2
    if issue_url and gh is not None:
        issue = gh.get_issue(issue_url)
        print(f"Fetched issue #{issue.number}: {issue.title}")

    try:
        task = build_task(issue, prompt)
    except ValueError as exc:
        _eprint(str(exc))
        return 2

    ctx = build_repo_context(repo_path, config)
    print(f"Loaded {len(ctx.instructions)} instruction file(s), {len(ctx.rules)} rule(s).")

    try:
        provider = get_provider(config)
    except LLMError as exc:
        _eprint(str(exc))
        return 2

    agent = Agent(provider, config, repo_path)

    print(f"\n== Planning ({config.provider}) ==")
    plan = agent.plan(workflow_text, ctx, task)
    print(plan.as_text())

    if dry_run:
        print("\n[dry-run] Stopping before making edits.")
        return 0

    feedback: str | None = None
    impl = None
    tests_passed = True
    test_output = ""
    for attempt in range(1, config.max_iterations + 1):
        print(f"\n== Implementing (attempt {attempt}/{config.max_iterations}) ==")
        impl = agent.implement(workflow_text, ctx, task, plan, feedback=feedback)
        from .editor import apply_edits

        changed = apply_edits(repo_path, impl.edits)
        print("Changes:\n  " + ("\n  ".join(changed) if changed else "(none)"))

        commands = impl.commands or ([config.test_command] if config.test_command else [])
        if not commands:
            print("No test command specified; skipping test run.")
            tests_passed = True
            break
        print(f"Running: {commands}")
        results = run_all(repo_path, commands)
        test_output = "\n\n".join(f"$ {r.command}\n{r.output}" for r in results)
        tests_passed = all(r.ok for r in results)
        if tests_passed:
            print("Tests passed.")
            break
        print("Tests failed; will ask the model to fix.")
        feedback = test_output[-6000:]

    if impl is None:
        _eprint("No implementation was produced.")
        return 1

    print(f"\nSummary: {impl.summary}")

    if not make_pr:
        print("\n[--no-pr] Leaving changes in the working tree without committing.")
        return 0 if tests_passed else 1

    if not has_changes(repo_path):
        _eprint("No file changes to commit; aborting PR.")
        return 1

    assert gh is not None
    import subprocess

    origin = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if not origin:
        _eprint("Target repo has no 'origin' remote; cannot open a PR.")
        return 1
    owner, repo = gh.parse_repo_url(origin)
    base_branch = base or gh.default_branch(owner, repo)

    create_branch(repo_path, impl.branch)
    commit_all(repo_path, impl.commit_message)
    assert config.github_token is not None
    set_remote(repo_path, _authed_remote(origin, config.github_token))
    push(repo_path, impl.branch)

    pr_url = gh.create_pull_request(
        owner=owner,
        repo=repo,
        title=impl.pr_title,
        head=impl.branch,
        base=base_branch,
        body=impl.pr_body,
    )
    print(f"\nOpened PR: {pr_url}")
    return 0 if tests_passed else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-agent", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--path", default=".", help="Path to the target repo (default: cwd)")
    common.add_argument("--base", default=None, help="Base branch for the PR")
    common.add_argument("--dry-run", action="store_true", help="Plan only; make no edits")
    common.add_argument("--no-pr", action="store_true", help="Apply + test but do not open a PR")
    common.add_argument(
        "--provider",
        default=None,
        help="Override LLM provider (anthropic|openai|openrouter|mock)",
    )

    p_list = sub.add_parser("list", help="List available workflows")
    p_list.add_argument("--path", default=".", help="Path to the target repo (default: cwd)")
    p_list.set_defaults(func=cmd_list)

    p_run = sub.add_parser("run", parents=[common], help="Run a named workflow")
    p_run.add_argument("workflow", help="Workflow name (matches .ai/workflows/<name>.md)")
    p_run.add_argument("--issue", default=None, help="GitHub issue URL")
    p_run.add_argument("--prompt", default=None, help="Free-form task description")

    p_wi = sub.add_parser("work-issue", parents=[common], help="Resolve a GitHub issue")
    p_wi.add_argument("issue", help="GitHub issue URL")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "list":
        return cmd_list(args)

    repo_path = Path(args.path).resolve()
    if args.command == "work-issue":
        return _run_workflow(
            repo_path=repo_path,
            workflow_name="work-issue",
            issue_url=args.issue,
            prompt=None,
            base=args.base,
            dry_run=args.dry_run,
            make_pr=not args.no_pr,
            provider_override=args.provider,
        )
    if args.command == "run":
        return _run_workflow(
            repo_path=repo_path,
            workflow_name=args.workflow,
            issue_url=args.issue,
            prompt=args.prompt,
            base=args.base,
            dry_run=args.dry_run,
            make_pr=not args.no_pr,
            provider_override=args.provider,
        )
    parser.error(f"Unknown command {args.command!r}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
