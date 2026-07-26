"""Conflict parsing, deterministic strategies and end-to-end merge resolution."""

import subprocess
from pathlib import Path

import pytest

from github_issue_agent import git_ops
from github_issue_agent.merge.conflicts import (
    has_conflict_markers,
    parse_conflicts,
)
from github_issue_agent.merge.resolver import detect_conflicts, resolve_conflicts, sync_with_base
from github_issue_agent.merge.strategies import resolve_block

TWO_WAY = """head
<<<<<<< HEAD
ours
=======
theirs
>>>>>>> feature
tail
"""

DIFF3 = """head
<<<<<<< HEAD
ours
||||||| base
common
=======
theirs
>>>>>>> feature
tail
"""


def _blocks(text):
    parsed = parse_conflicts(text)
    return [part for part in parsed.parts if not isinstance(part, str)]


def test_parse_two_way_markers():
    assert has_conflict_markers(TWO_WAY)
    block = _blocks(TWO_WAY)[0]
    assert block.ours == ["ours"]
    assert block.theirs == ["theirs"]
    assert block.base is None
    assert block.ours_label == "HEAD"


def test_parse_diff3_markers_keep_base():
    block = _blocks(DIFF3)[0]
    assert block.base == ["common"]
    assert block.ours == ["ours"] and block.theirs == ["theirs"]


def test_identical_and_whitespace_conflicts_resolve_deterministically():
    identical = _blocks(TWO_WAY.replace("theirs", "ours"))[0]
    assert resolve_block(identical).lines == ["ours"]

    whitespace = _blocks(TWO_WAY.replace("theirs", "ours  "))[0]
    resolution = resolve_block(whitespace)
    assert resolution.lines is not None
    assert [line.strip() for line in resolution.lines] == ["ours"]


def test_one_sided_change_uses_base():
    # Only "theirs" changed relative to the base -> take theirs.
    block = _blocks(DIFF3.replace("ours\n|||||||", "common\n|||||||"))[0]
    resolution = resolve_block(block)
    assert resolution.lines == ["theirs"]


def test_additive_imports_are_unioned():
    text = (
        "<<<<<<< HEAD\n"
        "import os\n"
        "import sys\n"
        "=======\n"
        "import os\n"
        "import json\n"
        ">>>>>>> feature\n"
    )
    resolution = resolve_block(_blocks(text)[0], path="app.py")
    assert resolution.lines is not None
    assert set(resolution.lines) == {"import os", "import sys", "import json"}


def test_semantic_conflict_is_escalated():
    text = (
        "<<<<<<< HEAD\n"
        "def rate(x):\n"
        "    return x * 2\n"
        "=======\n"
        "def rate(x):\n"
        "    return x * 3\n"
        ">>>>>>> feature\n"
    )
    assert resolve_block(_blocks(text)[0], path="app.py").lines is None


def test_prefer_forces_a_side():
    assert resolve_block(_blocks(TWO_WAY)[0], prefer="theirs").lines == ["theirs"]
    assert resolve_block(_blocks(TWO_WAY)[0], prefer="ours").lines == ["ours"]


# --- integration: real git repositories -------------------------------------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture()
def conflicting_repo(tmp_path):
    """A repo whose feature branch conflicts with main on an import list."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "agent@example.com")
    _git(repo, "config", "user.name", "agent")
    (repo / "app.py").write_text("import os\n\n\ndef main():\n    return 1\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "initial")

    _git(repo, "checkout", "-b", "feature")
    (repo / "app.py").write_text(
        "import os\nimport sys\n\n\ndef main():\n    return 1\n", encoding="utf-8"
    )
    _git(repo, "commit", "-am", "feature: import sys")

    _git(repo, "checkout", "main")
    (repo / "app.py").write_text(
        "import os\nimport json\n\n\ndef main():\n    return 1\n", encoding="utf-8"
    )
    _git(repo, "commit", "-am", "main: import json")
    _git(repo, "checkout", "feature")
    return repo


def test_detect_conflicts_reports_unmerged_paths(conflicting_repo):
    assert git_ops.would_conflict(conflicting_repo, "main") is True
    git_ops.merge(conflicting_repo, "main")
    assert detect_conflicts(conflicting_repo) == ["app.py"]
    git_ops.abort_merge(conflicting_repo)


def test_resolve_conflicts_unions_imports_and_commits(conflicting_repo):
    git_ops.merge(conflicting_repo, "main")
    result = resolve_conflicts(conflicting_repo)
    assert result.conflicted == ["app.py"]
    assert result.fully_resolved
    content = (conflicting_repo / "app.py").read_text(encoding="utf-8")
    assert "import sys" in content and "import json" in content
    assert not has_conflict_markers(content)


def test_sync_with_base_merges_and_validates(conflicting_repo):
    result = sync_with_base(
        conflicting_repo,
        "main",
        validation_commands=["python -c 'import ast,pathlib; ast.parse(open(\"app.py\").read())'"],
    )
    assert result.fully_resolved
    assert result.committed
    assert not git_ops.merge_in_progress(conflicting_repo)


def test_sync_with_base_aborts_when_resolution_is_impossible(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "agent@example.com")
    _git(repo, "config", "user.name", "agent")
    (repo / "app.py").write_text("def rate(x):\n    return x\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "initial")
    _git(repo, "checkout", "-b", "feature")
    (repo / "app.py").write_text("def rate(x):\n    return x * 2\n", encoding="utf-8")
    _git(repo, "commit", "-am", "feature")
    _git(repo, "checkout", "main")
    (repo / "app.py").write_text("def rate(x):\n    return x * 3\n", encoding="utf-8")
    _git(repo, "commit", "-am", "main")
    _git(repo, "checkout", "feature")

    # No LLM available: the semantic conflict cannot be resolved, so the merge
    # must be rolled back and the branch left exactly as it was.
    result = sync_with_base(repo, "main")
    assert result.unresolved_files == ["app.py"]
    assert not git_ops.merge_in_progress(repo)
    assert (repo / "app.py").read_text(encoding="utf-8") == "def rate(x):\n    return x * 2\n"
