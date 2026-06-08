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
from .api import AgentError, discover_workflows, run_workflow


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


def _make_printer() -> object:
    def on_event(kind: str, message: str) -> None:
        if kind == "plan":
            print("\n== Planning ==")
            print(message)
        elif kind == "implement" and message.startswith("attempt "):
            print(f"\n== Implementing ({message}) ==")
        elif kind == "implement":
            print("Changes:\n  " + message.replace("Changes: ", "").replace(", ", "\n  "))
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
            on_event=_make_printer(),  # type: ignore[arg-type]
        )
    except AgentError as exc:
        _eprint(str(exc))
        return 2

    if dry_run:
        print("\n[dry-run] Stopping before making edits.")
        return 0

    print(f"\nSummary: {result.summary}")
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
