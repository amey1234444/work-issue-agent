"""Command-line entrypoint.

The available commands are *data*, not code: every ``.ai/workflows/<name>.md`` in
the target repo becomes a runnable command. ``work-issue`` is provided as sugar
for ``run work-issue --issue <url>``.

Exit codes are stable (see :mod:`github_issue_agent.errors`): 0 success,
1 validation failed / blocked, 2 configuration, 3 authentication, 4 provider,
5 workspace or conflict, 6 publication, 7 cancelled, 8 budget, 9 internal.
"""

from __future__ import annotations

import argparse
import json
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from types import FrameType

from . import __version__
from .api import AgentError, WorkflowResult, discover_workflows, run_workflow
from .config import Config, ConfigError
from .errors import EXIT_CODES
from .runner import CancellationToken


def _eprint(msg: str) -> None:
    print(msg, file=sys.stderr)


# -- list ------------------------------------------------------------------------
def cmd_list(args: argparse.Namespace) -> int:
    repo_path = Path(args.path).resolve()
    workflows = discover_workflows(repo_path)
    if getattr(args, "json", False):
        print(json.dumps({"workflows": sorted(workflows)}, indent=2))
        return 0 if workflows else EXIT_CODES["configuration"]
    if not workflows:
        _eprint(f"No workflows found under {repo_path / '.ai' / 'workflows'}")
        return EXIT_CODES["configuration"]
    print("Available workflows:")
    for name, path in workflows.items():
        first_line = ""
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                first_line = line.lstrip("# ").strip()
                break
        print(f"  {name:<16} {first_line}")
    return 0


# -- init ------------------------------------------------------------------------
_INIT_CONFIG = """\
# Configuration for the work-issue-agent (ai-agent).
provider: openrouter          # anthropic | openai | openrouter | mock
max_iterations: 3

# Repository-required checks. Every command here must exit 0 on the final tree
# before a PR is opened; the model cannot skip or replace them.
test_command: pytest -q
checks:
  - ruff check .

require_validation: true      # never publish unvalidated changes
draft_pr: true
deadline_seconds: 3600
command_timeout: 1800
"""

_INIT_WORKFLOW = """\
# work-issue

Resolve the given GitHub issue.

1. Read the repository instructions (AGENTS.md, CONTRIBUTING.md, README.md).
2. Understand the issue and locate the relevant code.
3. Make the smallest correct change and add or update tests.
4. Make sure the repository's required checks pass.
5. Summarise the change for the pull request and reference the issue.
"""

_INIT_RULES = """\
# Coding rules

- Keep changes minimal and focused.
- Never modify generated files or secrets.
- Every behavioural change needs a test.
"""


def cmd_init(args: argparse.Namespace) -> int:
    repo_path = Path(args.path).resolve()
    created: list[str] = []
    targets = {
        repo_path / ".ai" / "config.yaml": _INIT_CONFIG,
        repo_path / ".ai" / "workflows" / "work-issue.md": _INIT_WORKFLOW,
        repo_path / ".ai" / "rules" / "coding.md": _INIT_RULES,
    }
    for target, content in targets.items():
        if target.exists() and not args.force:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        created.append(str(target.relative_to(repo_path)))
    gitignore = repo_path / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if ".agent_work/" not in existing:
        with gitignore.open("a", encoding="utf-8") as fh:
            if existing and not existing.endswith("\n"):
                fh.write("\n")
            fh.write(".agent_work/\n")
        created.append(".gitignore")
    if args.json:
        print(json.dumps({"created": created}, indent=2))
    else:
        for item in created:
            print(f"created {item}")
        if not created:
            print("Nothing to do; configuration already present (use --force to overwrite).")
    return 0


# -- doctor ----------------------------------------------------------------------
def _doctor_checks(repo_path: Path) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []

    def add(name: str, ok: bool, detail: str, *, fatal: bool = True) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail, "fatal": fatal})

    add("python", sys.version_info >= (3, 10), sys.version.split()[0])
    git = shutil.which("git")
    add("git", git is not None, git or "git not found on PATH")
    if git:
        proc = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"], cwd=repo_path, capture_output=True, text=True
        )
        add("git repository", proc.returncode == 0, repo_path.as_posix(), fatal=False)
        if proc.returncode == 0:
            remote = subprocess.run(
                ["git", "remote", "get-url", "origin"], cwd=repo_path, capture_output=True, text=True
            ).stdout.strip()
            add("origin remote", bool(remote), remote or "no origin remote", fatal=False)

    workflows = discover_workflows(repo_path)
    add("workflows", bool(workflows), ", ".join(workflows) or "none (run `ai-agent init`)")

    try:
        cfg = Config.load(repo_path)
        cfg.validate()
        add("config", True, f"provider={cfg.provider} model={cfg.model}")
        add(
            "required checks",
            bool(cfg.required_checks),
            ", ".join(cfg.required_checks) or "none configured; PRs will be blocked",
            fatal=False,
        )
        for cmd in cfg.required_checks:
            exe = cmd.split()[0] if cmd.split() else ""
            add(f"check tool: {exe}", shutil.which(exe) is not None, cmd, fatal=False)
        key = cfg.resolve_api_key()
        add(
            "provider api key",
            cfg.provider == "mock" or key is not None,
            "present" if key else "missing",
        )
        add("github token", cfg.github_token is not None, "present" if cfg.github_token else "missing", fatal=False)
    except ConfigError as exc:
        add("config", False, str(exc))
    return checks


def cmd_doctor(args: argparse.Namespace) -> int:
    repo_path = Path(args.path).resolve()
    checks = _doctor_checks(repo_path)
    failed = [c for c in checks if not c["ok"] and c["fatal"]]
    if args.json:
        print(json.dumps({"ok": not failed, "checks": checks}, indent=2))
    else:
        for c in checks:
            mark = "ok  " if c["ok"] else ("FAIL" if c["fatal"] else "warn")
            print(f"[{mark}] {c['name']}: {c['detail']}")
    return 0 if not failed else EXIT_CODES["configuration"]


# -- run -------------------------------------------------------------------------
def _make_printer(quiet: bool) -> object:
    def on_event(kind: str, message: str) -> None:
        if quiet:
            return
        if kind == "plan":
            print("\n== Planning ==", file=sys.stderr)
            print(message, file=sys.stderr)
        elif kind == "implement" and message.startswith("attempt "):
            print(f"\n== Implementing ({message}) ==", file=sys.stderr)
        elif kind == "implement":
            print(message.replace("Changes: ", "Changes:\n  ").replace(", ", "\n  "), file=sys.stderr)
        elif kind == "pr":
            print(f"\n{message}", file=sys.stderr)
        else:
            print(message, file=sys.stderr)

    return on_event


def _install_cancel(token: CancellationToken) -> None:
    def handler(signum: int, frame: FrameType | None) -> None:
        token.cancel()
        _eprint("\nCancellation requested; stopping after the current step...")

    try:
        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)
    except ValueError:
        pass


def _print_result(result: WorkflowResult, *, as_json: bool, make_pr: bool, dry_run: bool) -> None:
    if as_json:
        print(json.dumps(result.as_dict(), indent=2))
        return
    if dry_run:
        print("\n[dry-run] Stopping before making edits.")
        return
    print(f"\nrun id:     {result.run_id}")
    print(f"summary:    {result.summary}")
    print(f"validation: {result.validation.status.value}")
    if result.pr_url:
        print(f"pr:         {result.pr_url}")
    elif not make_pr:
        print("\n[--no-pr] Changes were not committed or pushed.")
        if result.workspace:
            print(f"workspace:  {result.workspace}")


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
    model_override: str | None,
    as_json: bool,
    no_isolate: bool,
    allow_unvalidated: bool,
) -> int:
    token = CancellationToken()
    _install_cancel(token)
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
            model=model_override,
            isolate=not no_isolate,
            allow_unvalidated=allow_unvalidated,
            cancel=token,
            on_event=_make_printer(quiet=False),  # type: ignore[arg-type]
        )
    except AgentError as exc:
        if as_json:
            print(json.dumps(exc.as_dict(), indent=2))
        else:
            _eprint(f"error [{exc.code}]: {exc}")
            if exc.recovery:
                _eprint(f"recovery: {exc.recovery}")
        return exc.exit_code

    _print_result(result, as_json=as_json, make_pr=make_pr, dry_run=dry_run)
    if dry_run:
        return 0
    return 0 if result.tests_passed else EXIT_CODES["validation"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-agent", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--path", default=".", help="Path to the target repo (default: cwd)")
    common.add_argument("--json", action="store_true", help="Print a machine-readable JSON result")

    run_common = argparse.ArgumentParser(add_help=False, parents=[common])
    run_common.add_argument("--base", default=None, help="Base branch for the PR")
    run_common.add_argument("--dry-run", action="store_true", help="Plan only; make no edits")
    run_common.add_argument("--no-pr", action="store_true", help="Apply + validate but do not open a PR")
    run_common.add_argument(
        "--provider",
        default=None,
        help="Override LLM provider (anthropic|openai|openrouter|mock)",
    )
    run_common.add_argument("--model", default=None, help="Override the model name")
    run_common.add_argument(
        "--no-isolate",
        action="store_true",
        help="Edit the checkout in place instead of a disposable worktree (not recommended)",
    )
    run_common.add_argument(
        "--allow-unvalidated",
        action="store_true",
        help="Open a PR even when validation did not pass (not recommended)",
    )

    p_list = sub.add_parser("list", parents=[common], help="List available workflows")
    p_list.set_defaults(func=cmd_list)

    p_init = sub.add_parser("init", parents=[common], help="Scaffold .ai/ configuration in a repo")
    p_init.add_argument("--force", action="store_true", help="Overwrite existing files")
    p_init.set_defaults(func=cmd_init)

    p_doc = sub.add_parser("doctor", parents=[common], help="Check the environment and configuration")
    p_doc.set_defaults(func=cmd_doctor)

    p_run = sub.add_parser("run", parents=[run_common], help="Run a named workflow")
    p_run.add_argument("workflow", help="Workflow name (matches .ai/workflows/<name>.md)")
    p_run.add_argument("--issue", default=None, help="GitHub issue URL")
    p_run.add_argument("--prompt", default=None, help="Free-form task description")

    p_wi = sub.add_parser("work-issue", parents=[run_common], help="Resolve a GitHub issue")
    p_wi.add_argument("issue", help="GitHub issue URL")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command in ("list", "init", "doctor"):
        return int(args.func(args))

    repo_path = Path(args.path).resolve()
    if args.command == "work-issue":
        issue_url: str | None = args.issue
        prompt: str | None = None
        workflow_name = "work-issue"
    elif args.command == "run":
        issue_url = args.issue
        prompt = args.prompt
        workflow_name = args.workflow
    else:  # pragma: no cover
        parser.error(f"Unknown command {args.command!r}")
        return EXIT_CODES["configuration"]

    return _run_workflow(
        repo_path=repo_path,
        workflow_name=workflow_name,
        issue_url=issue_url,
        prompt=prompt,
        base=args.base,
        dry_run=args.dry_run,
        make_pr=not args.no_pr,
        provider_override=args.provider,
        model_override=args.model,
        as_json=args.json,
        no_isolate=args.no_isolate,
        allow_unvalidated=args.allow_unvalidated,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
