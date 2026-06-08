"""Run shell commands (tests, linters) inside the target repo and capture output."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CommandResult:
    command: str
    exit_code: int
    output: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


def run_command(repo_path: Path, command: str, timeout: int = 1800) -> CommandResult:
    """Run a single shell command, merging stdout/stderr."""
    try:
        proc = subprocess.run(
            command,
            cwd=repo_path,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        return CommandResult(command=command, exit_code=proc.returncode, output=output)
    except subprocess.TimeoutExpired:
        return CommandResult(command=command, exit_code=124, output=f"Timed out after {timeout}s")


def run_all(repo_path: Path, commands: list[str]) -> list[CommandResult]:
    """Run commands in order, stopping at the first failure."""
    results: list[CommandResult] = []
    for cmd in commands:
        result = run_command(repo_path, cmd)
        results.append(result)
        if not result.ok:
            break
    return results
