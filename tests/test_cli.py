from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from github_issue_agent import EXIT_CODES
from github_issue_agent.cli import main

PY = sys.executable


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "README.md").write_text("hi\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def test_init_scaffolds_and_is_idempotent(tmp_path, capsys):
    repo = _init_repo(tmp_path)
    assert main(["init", "--path", str(repo)]) == 0
    assert (repo / ".ai" / "config.yaml").is_file()
    assert (repo / ".ai" / "workflows" / "work-issue.md").is_file()
    assert (repo / ".ai" / "rules" / "coding.md").is_file()
    assert ".agent_work/" in (repo / ".gitignore").read_text()
    (repo / ".ai" / "config.yaml").write_text("provider: mock\n")
    assert main(["init", "--path", str(repo)]) == 0
    assert (repo / ".ai" / "config.yaml").read_text() == "provider: mock\n"  # not overwritten
    assert main(["init", "--path", str(repo), "--force"]) == 0
    assert (repo / ".ai" / "config.yaml").read_text() != "provider: mock\n"
    capsys.readouterr()


def test_doctor_json_reports_problems(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_PAT", raising=False)
    repo = _init_repo(tmp_path)
    code = main(["doctor", "--path", str(repo), "--json"])
    out = json.loads(capsys.readouterr().out)
    names = {c["name"]: c for c in out["checks"]}
    assert code == EXIT_CODES["configuration"]
    assert out["ok"] is False
    assert names["workflows"]["ok"] is False
    assert names["git repository"]["ok"] is True

    main(["init", "--path", str(repo)])
    (repo / ".ai" / "config.yaml").write_text(f"provider: mock\ntest_command: {PY} -c 'print(1)'\n")
    capsys.readouterr()
    code = main(["doctor", "--path", str(repo), "--json"])
    out = json.loads(capsys.readouterr().out)
    names = {c["name"]: c for c in out["checks"]}
    assert code == 0 and out["ok"] is True
    assert names["workflows"]["ok"] is True
    assert names["github token"]["ok"] is False and names["github token"]["fatal"] is False


def test_run_json_no_pr_and_exit_codes(tmp_path, capsys):
    repo = _init_repo(tmp_path)
    main(["init", "--path", str(repo)])
    (repo / ".ai" / "config.yaml").write_text(f"provider: mock\ntest_command: {PY} -c 'print(1)'\n")
    capsys.readouterr()

    code = main(["run", "work-issue", "--path", str(repo), "--prompt", "x", "--no-pr", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["status"] == "validated"
    assert out["validation"]["status"] == "passed"
    assert out["run_id"] and out["workspace"]
    assert [c["path"] for c in out["changes"]] == ["AGENT_NOTES.md"]
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"

    # Failing required check -> validation exit code, evidence in the JSON result.
    (repo / ".ai" / "config.yaml").write_text(f"provider: mock\ntest_command: {PY} -c 'raise SystemExit(3)'\n")
    code = main(["run", "work-issue", "--path", str(repo), "--prompt", "x", "--no-pr", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert code == EXIT_CODES["validation"]
    assert out["validation"]["status"] == "failed"
    assert out["validation"]["checks"][0]["exit_code"] == 3
    assert out["pr_url"] is None


def test_dry_run_and_unknown_workflow(tmp_path, capsys):
    repo = _init_repo(tmp_path)
    main(["init", "--path", str(repo)])
    (repo / ".ai" / "config.yaml").write_text("provider: mock\n")
    capsys.readouterr()
    assert main(["run", "work-issue", "--path", str(repo), "--prompt", "x", "--dry-run", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True and out["changes"] == []

    code = main(["run", "nope", "--path", str(repo), "--prompt", "x", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert code == EXIT_CODES["configuration"]
    assert out["code"] == "configuration"


def test_missing_provider_key_is_configuration_error(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    repo = _init_repo(tmp_path)
    main(["init", "--path", str(repo)])
    (repo / ".ai" / "config.yaml").write_text("provider: openai\n")
    capsys.readouterr()
    code = main(["run", "work-issue", "--path", str(repo), "--prompt", "x", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert code in (EXIT_CODES["configuration"], EXIT_CODES["authentication"], EXIT_CODES["provider"])
    assert out["code"] in ("configuration", "authentication", "provider")
