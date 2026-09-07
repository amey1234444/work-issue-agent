"""Run checks (tests, linters) inside the workspace and capture bounded output.

Commands are executed without a shell (``shlex.split`` -> argv), in their own
process group so a timeout or cancellation kills every child, with a scrubbed
environment that never contains publishing or provider credentials, and with
stdout/stderr capped so a chatty test suite cannot exhaust memory.
"""

from __future__ import annotations

import os
import re
import shlex
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

# Environment variable names that must never reach a model-chosen command.
_SECRET_ENV_RE = re.compile(
    r"(TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|APIKEY|PRIVATE_KEY|CREDENTIALS?|GITHUB_PAT)",
    re.IGNORECASE,
)
_ALWAYS_STRIP = {"GIT_ASKPASS", "SSH_AUTH_SOCK", "GH_TOKEN"}


class CancellationToken:
    """Thread-safe flag a UI can set to stop a run at the next safe boundary."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


@dataclass
class Deadline:
    """Absolute wall-clock budget for a run."""

    seconds: float
    started: float = field(default_factory=time.monotonic)

    @property
    def remaining(self) -> float:
        return max(0.0, self.seconds - (time.monotonic() - self.started))

    @property
    def expired(self) -> bool:
        return self.remaining <= 0


def scrubbed_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Return a copy of the environment without anything that looks like a secret."""
    src = os.environ if base is None else base
    env = {k: v for k, v in src.items() if not _SECRET_ENV_RE.search(k) and k not in _ALWAYS_STRIP}
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


@dataclass
class CommandResult:
    command: str
    exit_code: int
    output: str
    argv: list[str] = field(default_factory=list)
    started_at: float = 0.0
    ended_at: float = 0.0
    truncated: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    @property
    def duration(self) -> float:
        return max(0.0, self.ended_at - self.started_at)


def _kill_group(proc: subprocess.Popen[bytes]) -> None:
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:  # pragma: no cover - windows
            proc.kill()
    except (ProcessLookupError, PermissionError):
        pass


def run_command(
    repo_path: Path,
    command: str,
    timeout: float = 1800,
    *,
    max_output_chars: int = 200_000,
    env: dict[str, str] | None = None,
    cancel: CancellationToken | None = None,
    poll_interval: float = 0.2,
) -> CommandResult:
    """Run one command (no shell) and return its merged, bounded output."""
    started = time.time()
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return CommandResult(command, 127, f"Could not parse command: {exc}", [], started, time.time())
    if not argv:
        return CommandResult(command, 127, "Empty command", [], started, time.time())

    try:
        proc = subprocess.Popen(
            argv,
            cwd=repo_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=env if env is not None else scrubbed_env(),
            start_new_session=(os.name == "posix"),
        )
    except FileNotFoundError:
        return CommandResult(
            command, 127, f"Command not found: {argv[0]}", argv, started, time.time()
        )
    except OSError as exc:
        return CommandResult(command, 126, f"Could not start command: {exc}", argv, started, time.time())

    chunks: list[bytes] = []
    size = 0
    truncated = False
    assert proc.stdout is not None
    stdout = proc.stdout

    def _reader() -> None:
        nonlocal size, truncated
        for block in iter(lambda: stdout.read(65536), b""):
            if size < max_output_chars:
                chunks.append(block)
                size += len(block)
            else:
                truncated = True
        stdout.close()

    reader = threading.Thread(target=_reader, daemon=True)
    reader.start()

    exit_code: int
    reason = ""
    while True:
        rc = proc.poll()
        if rc is not None:
            exit_code = rc
            break
        if cancel is not None and cancel.cancelled:
            _kill_group(proc)
            proc.wait()
            exit_code, reason = 130, "Cancelled"
            break
        if time.time() - started > timeout:
            _kill_group(proc)
            proc.wait()
            exit_code, reason = 124, f"Timed out after {int(timeout)}s"
            break
        time.sleep(poll_interval)
    reader.join(timeout=5)

    output = b"".join(chunks).decode("utf-8", errors="replace")
    if len(output) > max_output_chars:
        output, truncated = output[:max_output_chars], True
    if truncated:
        output += "\n... [output truncated]\n"
    if reason:
        output = (output + "\n" if output else "") + reason
    return CommandResult(command, exit_code, output, argv, started, time.time(), truncated)


def run_all(
    repo_path: Path,
    commands: list[str],
    *,
    timeout: float = 1800,
    max_output_chars: int = 200_000,
    cancel: CancellationToken | None = None,
    deadline: Deadline | None = None,
    on_start: Callable[[str], None] | None = None,
) -> list[CommandResult]:
    """Run commands in order, stopping at the first failure or when out of budget."""
    results: list[CommandResult] = []
    env = scrubbed_env()
    for cmd in commands:
        if cancel is not None and cancel.cancelled:
            break
        per_cmd = timeout
        if deadline is not None:
            if deadline.expired:
                break
            per_cmd = min(timeout, deadline.remaining)
        if on_start is not None:
            on_start(cmd)
        result = run_command(
            repo_path,
            cmd,
            per_cmd,
            max_output_chars=max_output_chars,
            env=env,
            cancel=cancel,
        )
        results.append(result)
        if not result.ok:
            break
    return results
