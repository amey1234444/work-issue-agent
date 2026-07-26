"""Which shell commands the agent may run, and how their output is captured."""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

#: Executables the agent may invoke without operator approval. Everything here
#: inspects, builds, tests or lints; nothing publishes, deletes or mutates
#: remote state.
DEFAULT_ALLOWED = {
    "pytest", "python", "python3", "py.test", "tox", "nox", "coverage",
    "ruff", "black", "isort", "flake8", "mypy", "pyright", "pylint",
    "npm", "npx", "yarn", "pnpm", "node", "tsc", "eslint", "prettier", "vitest", "jest",
    "go", "cargo", "make", "just", "mvn", "gradle", "dotnet", "rspec", "bundle", "rake",
    "git", "ls", "cat", "head", "tail", "wc", "grep", "rg", "find", "sed", "awk", "diff", "echo",
    "uv", "poetry", "pip", "pipx", "hatch", "pdm",
}

#: git subcommands that publish or destroy work; the agent must use the
#: dedicated git helpers (which are auditable) instead of shelling out.
_FORBIDDEN_GIT_SUBCOMMANDS = {"push", "reset", "clean", "gc", "filter-branch", "remote"}

_SHELL_METACHARACTERS = {"|", "&", ";", ">", "<", "`", "$(", "&&", "||", ">>"}


class CommandNotAllowed(RuntimeError):
    pass


@dataclass
class CommandResult:
    command: str
    exit_code: int
    output: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


def split_command(command: str | list[str]) -> list[str]:
    if isinstance(command, list):
        return [str(part) for part in command]
    return shlex.split(command)


def check_allowed(command: str | list[str], extra_allowed: list[str] | None = None) -> list[str]:
    """Validate a command against the allowlist, returning its argv.

    Raises :class:`CommandNotAllowed` with an explanation the model can act on.
    """
    if isinstance(command, str):
        for meta in _SHELL_METACHARACTERS:
            if meta in command:
                raise CommandNotAllowed(
                    f"Shell metacharacter {meta!r} is not allowed. "
                    "Pass a plain argv list and run one command per call."
                )
    argv = split_command(command)
    if not argv:
        raise CommandNotAllowed("Empty command")

    program = Path(argv[0]).name
    allowed = DEFAULT_ALLOWED | set(extra_allowed or [])
    if program not in allowed:
        raise CommandNotAllowed(
            f"Command {program!r} is not on the approved list. Allowed: "
            + ", ".join(sorted(allowed)[:25])
            + ", ..."
        )
    if program == "git" and len(argv) > 1 and argv[1] in _FORBIDDEN_GIT_SUBCOMMANDS:
        raise CommandNotAllowed(
            f"'git {argv[1]}' is not permitted from run_command; the harness owns "
            "branching, pushing and remotes."
        )
    return argv


def run(
    repo_path: Path,
    command: str | list[str],
    *,
    timeout: int = 900,
    extra_allowed: list[str] | None = None,
) -> CommandResult:
    """Run an approved command in the repo, merging stdout and stderr."""
    argv = check_allowed(command, extra_allowed)
    printable = " ".join(shlex.quote(part) for part in argv)
    try:
        proc = subprocess.run(
            argv,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return CommandResult(printable, 127, f"Executable not found: {argv[0]}")
    except subprocess.TimeoutExpired:
        return CommandResult(printable, 124, f"Timed out after {timeout}s", timed_out=True)
    return CommandResult(printable, proc.returncode, (proc.stdout or "") + (proc.stderr or ""))
