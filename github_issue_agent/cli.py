"""Command-line entrypoint.

The available commands are *data*, not code: every ``.ai/workflows/<name>.md`` in
the target repo becomes a runnable command. ``work-issue`` is provided as sugar
for ``run work-issue --issue <url>``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .api import (
    AgentError,
    discover_workflows,
    fix_pull_request_conflicts,
    resolve_conflicts,
    run_workflow,
)
from .repo_map import build_repo_map


def _eprint(msg: str) -> None:
    print(msg, file=sys.stderr)


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


def cmd_map(args: argparse.Namespace) -> int:
    """Print the repository map the agent starts from (no LLM call)."""
    repo_map = build_repo_map(Path(args.path).resolve())
    print(repo_map.as_context_block())
    return 0


def _make_printer(verbose: bool = False) -> object:
    def on_event(kind: str, message: str) -> None:
        if kind == "plan":
            print("\n== Planning ==")
            print(message)
        elif kind == "tool":
            if verbose:
                print(f"  · {message}")
        elif kind == "implement" and message.startswith("attempt "):
            print(f"\n== Implementing ({message}) ==")
        elif kind == "implement":
            print("Changes:\n  " + message.replace("Changes: ", "").replace(", ", "\n  "))
        elif kind == "integrity":
            _eprint(f"\n!! Integrity warning:\n{message}")
        elif kind == "pr":
            print(f"\n{message}")
        else:
            print(message)

    return on_event


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
    mode: str | None = None,
    max_steps: int | None = None,
    verbose: bool = False,
) -> int:
    try:
        result = run_workflow(
            workflow_name,
            repo_path=repo_path,
            issue_url=issue_url,
            prompt=prompt,
            base=base,
            dry_run=dry_run,
            open_pr=make_pr,
            provider=provider_override,
            mode=mode,
            max_steps=max_steps,
            on_event=_make_printer(verbose),  # type: ignore[arg-type]
        )
    except AgentError as exc:
        _eprint(str(exc))
        return 2

    if dry_run:
        print("\n[dry-run] Stopping before making edits.")
        return 0

    print(f"\nSummary: {result.summary}")
    if result.integrity_warnings:
        _eprint("Integrity warnings:\n  " + "\n  ".join(result.integrity_warnings))
    if result.conflicts is not None and result.conflicts.conflicted:
        print("\n" + result.conflicts.report())
    if not make_pr:
        print("\n[--no-pr] Leaving changes in the working tree without committing.")
    return 0 if result.tests_passed else 1


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
    common.add_argument(
        "--mode",
        choices=["agent", "workflow"],
        default=None,
        help="agent: Codex-style tool loop (default); workflow: legacy plan/implement",
    )
    common.add_argument(
        "--max-steps",
        type=int,
        default=None,
        help="Maximum tool calls in agent mode (default: 60)",
    )
    common.add_argument("-v", "--verbose", action="store_true", help="Print every tool call")

    p_list = sub.add_parser("list", help="List available workflows")
    p_list.add_argument("--path", default=".", help="Path to the target repo (default: cwd)")
    p_list.set_defaults(func=cmd_list)

    p_run = sub.add_parser("run", parents=[common], help="Run a named workflow")
    p_run.add_argument("workflow", help="Workflow name (matches .ai/workflows/<name>.md)")
    p_run.add_argument("--issue", default=None, help="GitHub issue URL")
    p_run.add_argument("--prompt", default=None, help="Free-form task description")

    p_wi = sub.add_parser("work-issue", parents=[common], help="Resolve a GitHub issue")
    p_wi.add_argument("issue", help="GitHub issue URL")

    p_map = sub.add_parser("map", help="Print the repository map the agent starts from")
    p_map.add_argument("--path", default=".", help="Path to the target repo (default: cwd)")
    p_map.set_defaults(func=cmd_map)

    p_rc = sub.add_parser(
        "resolve-conflicts",
        help="Detect and automatically resolve merge conflicts",
    )
    p_rc.add_argument("--path", default=".", help="Path to the target repo (default: cwd)")
    p_rc.add_argument(
        "--base",
        default=None,
        help="Merge/rebase this ref in first (e.g. main or origin/main)",
    )
    p_rc.add_argument(
        "--strategy", choices=["merge", "rebase"], default="merge", help="How to integrate --base"
    )
    p_rc.add_argument(
        "--prefer",
        choices=["ours", "theirs"],
        default=None,
        help="Force a side instead of resolving each hunk on its merits",
    )
    p_rc.add_argument("--guidance", default="", help="Extra instructions for semantic conflicts")
    p_rc.add_argument("--no-llm", action="store_true", help="Deterministic strategies only")
    p_rc.add_argument("--no-commit", action="store_true", help="Resolve but do not commit")
    p_rc.add_argument("--push", action="store_true", help="Push the branch after resolving")
    p_rc.add_argument("--provider", default=None, help="Override LLM provider")
    p_rc.add_argument("-v", "--verbose", action="store_true", help="Print every tool call")

    p_fix = sub.add_parser(
        "fix-pr",
        help="Resolve a pull request's conflicts with its base branch and push",
    )
    p_fix.add_argument("pr", help="GitHub pull request URL")
    p_fix.add_argument("--path", default=".", help="Path to the target repo (default: cwd)")
    p_fix.add_argument("--prefer", choices=["ours", "theirs"], default=None)
    p_fix.add_argument("--guidance", default="", help="Extra instructions for semantic conflicts")
    p_fix.add_argument("--no-push", action="store_true", help="Resolve locally without pushing")
    p_fix.add_argument("--comment", action="store_true", help="Comment the report on the PR")
    p_fix.add_argument("--provider", default=None, help="Override LLM provider")
    p_fix.add_argument("-v", "--verbose", action="store_true", help="Print every tool call")

    return parser


def cmd_resolve_conflicts(args: argparse.Namespace) -> int:
    try:
        result = resolve_conflicts(
            repo_path=Path(args.path).resolve(),
            base=args.base,
            strategy=args.strategy,
            prefer=args.prefer,
            guidance=args.guidance,
            provider=args.provider,
            use_llm=not args.no_llm,
            commit=not args.no_commit,
            push_branch=args.push,
            on_event=_make_printer(args.verbose),  # type: ignore[arg-type]
        )
    except (AgentError, RuntimeError) as exc:
        _eprint(str(exc))
        return 2
    print("\n" + result.report())
    if not result.conflicted:
        return 0
    return 0 if result.fully_resolved and result.validation_passed is not False else 1


def cmd_fix_pr(args: argparse.Namespace) -> int:
    try:
        result = fix_pull_request_conflicts(
            args.pr,
            repo_path=Path(args.path).resolve(),
            provider=args.provider,
            prefer=args.prefer,
            guidance=args.guidance,
            push_branch=not args.no_push,
            comment=args.comment,
            on_event=_make_printer(args.verbose),  # type: ignore[arg-type]
        )
    except (AgentError, RuntimeError) as exc:
        _eprint(str(exc))
        return 2
    print("\n" + result.report())
    return 0 if result.fully_resolved or not result.conflicted else 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "list":
        return cmd_list(args)
    if args.command == "map":
        return cmd_map(args)
    if args.command == "resolve-conflicts":
        return cmd_resolve_conflicts(args)
    if args.command == "fix-pr":
        return cmd_fix_pr(args)

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
            mode=args.mode,
            max_steps=args.max_steps,
            verbose=args.verbose,
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
            mode=args.mode,
            max_steps=args.max_steps,
            verbose=args.verbose,
        )
    parser.error(f"Unknown command {args.command!r}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
