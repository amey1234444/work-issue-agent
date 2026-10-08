import subprocess
import sys
import threading
import time

from github_issue_agent.runner import (
    CancellationToken,
    Deadline,
    run_all,
    run_command,
    scrubbed_env,
)

PY = sys.executable


def test_run_command_no_shell(tmp_path):
    # Shell metacharacters are passed literally, not interpreted.
    res = run_command(tmp_path, f"{PY} -c 'import sys; print(sys.argv[1:])' 'a;b' '$HOME'")
    assert res.ok
    assert "['a;b', '$HOME']" in res.output
    assert res.argv[0] == PY
    assert res.ended_at >= res.started_at


def test_run_command_missing_binary_is_reported(tmp_path):
    res = run_command(tmp_path, "definitely-not-a-real-binary-xyz --flag")
    assert res.exit_code == 127
    assert "not found" in res.output.lower()


def test_run_command_bad_quoting(tmp_path):
    res = run_command(tmp_path, "echo 'unterminated")
    assert not res.ok


def test_output_is_bounded(tmp_path):
    res = run_command(tmp_path, f"{PY} -c 'print(\"x\" * 50000)'", max_output_chars=1000)
    assert res.truncated
    assert len(res.output) < 1500
    assert "truncated" in res.output.lower()


def test_secret_env_is_scrubbed(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-secret")
    monkeypatch.setenv("MY_PASSWORD", "pw")
    monkeypatch.setenv("SAFE_VAR", "ok")
    env = scrubbed_env()
    assert "GITHUB_TOKEN" not in env and "OPENROUTER_API_KEY" not in env and "MY_PASSWORD" not in env
    assert env["SAFE_VAR"] == "ok"
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    res = run_command(tmp_path, f"{PY} -c 'import os; print(sorted(k for k in os.environ if \"TOKEN\" in k))'")
    assert res.output.strip() == "[]"


def test_timeout_kills_process_group(tmp_path):
    marker = tmp_path / "child.pid"
    script = (
        "import subprocess, sys, time, pathlib;"
        f"p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']);"
        f"pathlib.Path({str(marker)!r}).write_text(str(p.pid)); time.sleep(30)"
    )
    started = time.monotonic()
    res = run_command(tmp_path, f"{PY} -c \"{script}\"", timeout=1.0, poll_interval=0.05)
    assert res.exit_code == 124
    assert time.monotonic() - started < 10
    assert "timed out" in res.output.lower()
    child_pid = int(marker.read_text())
    # give the kernel a moment to reap
    for _ in range(50):
        alive = subprocess.run(["kill", "-0", str(child_pid)], capture_output=True).returncode == 0
        if not alive:
            break
        time.sleep(0.05)
    assert not alive, "grandchild process survived the timeout"


def test_cancellation_stops_command_and_skips_rest(tmp_path):
    token = CancellationToken()
    threading.Timer(0.3, token.cancel).start()
    results = run_all(
        tmp_path,
        [f"{PY} -c 'import time; time.sleep(20)'", f"{PY} -c 'print(1)'"],
        cancel=token,
    )
    assert results[0].exit_code == 130
    assert "cancel" in results[0].output.lower()
    assert len(results) == 1


def test_deadline_bounds_total_time(tmp_path):
    deadline = Deadline(seconds=0.5)
    results = run_all(tmp_path, [f"{PY} -c 'import time; time.sleep(20)'", f"{PY} -c 'print(1)'"], deadline=deadline)
    assert results[0].exit_code == 124
    assert len(results) == 1
    assert deadline.expired
