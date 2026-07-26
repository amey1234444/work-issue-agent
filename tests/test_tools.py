"""Tests for the tool layer: bounded reads, search, patching and commands."""

import pytest

from github_issue_agent.tools import ToolRegistry, default_registry
from github_issue_agent.tools.base import ToolContext, ToolError
from github_issue_agent.tools.fs import ListFilesTool, ReadFileTool
from github_issue_agent.tools.patch import ApplyPatchTool
from github_issue_agent.tools.plan import PlanBoard, UpdatePlanTool
from github_issue_agent.tools.search import FindReferencesTool, FindSymbolTool, SearchCodeTool
from github_issue_agent.tools.shell import ReadCommandOutputTool, RunCommandTool


@pytest.fixture()
def repo(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "core.py").write_text(
        "def greet(name):\n    return f'hi {name}'\n\n\nclass Greeter:\n    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "main.py").write_text("from pkg.core import greet\n\nprint(greet('x'))\n", "utf-8")
    return tmp_path


@pytest.fixture()
def ctx(repo):
    return ToolContext(repo_path=repo)


def test_read_file_returns_numbered_lines(ctx):
    out = ReadFileTool().run(ctx, path="pkg/core.py")
    assert "1| def greet(name):" in out
    assert "5| class Greeter:" in out


def test_read_file_range_and_truncation(ctx, repo):
    (repo / "big.txt").write_text("\n".join(f"line{i}" for i in range(1000)), encoding="utf-8")
    out = ReadFileTool().run(ctx, path="big.txt")
    assert "truncated" in out.lower()
    assert "read_file" in out  # tells the model how to continue
    window = ReadFileTool().run(ctx, path="big.txt", start_line=10, end_line=12)
    assert "line9" in window and "line12" not in window


def test_read_file_rejects_escape_and_missing(ctx):
    with pytest.raises(ToolError):
        ReadFileTool().run(ctx, path="../etc/passwd")
    with pytest.raises(ToolError):
        ReadFileTool().run(ctx, path="nope.py")


def test_list_files_glob(ctx):
    out = ListFilesTool().run(ctx, glob="**/*.py")
    assert "pkg/core.py" in out and "main.py" in out


def test_search_code_reports_paths_and_lines(ctx):
    out = SearchCodeTool().run(ctx, query="greet")
    assert "pkg/core.py:1" in out
    assert "def greet" in out


def test_find_symbol_and_references(ctx):
    assert "pkg/core.py" in FindSymbolTool().run(ctx, name="Greeter")
    refs = FindReferencesTool().run(ctx, name="greet")
    assert "main.py" in refs


def test_apply_patch_tool_records_paths(ctx, repo):
    patch = (
        "*** Begin Patch\n"
        "*** Update File: pkg/core.py\n"
        "@@\n"
        " def greet(name):\n"
        "-    return f'hi {name}'\n"
        "+    return f'hello {name}'\n"
        "*** End Patch\n"
    )
    out = ApplyPatchTool().run(ctx, patch=patch)
    assert "pkg/core.py" in out
    assert "hello" in (repo / "pkg" / "core.py").read_text(encoding="utf-8")
    assert ctx.patched_paths == ["pkg/core.py"]


def test_apply_patch_tool_reports_bad_context(ctx):
    patch = (
        "*** Begin Patch\n"
        "*** Update File: pkg/core.py\n"
        "@@\n"
        " nonexistent context\n"
        "+new\n"
        "*** End Patch\n"
    )
    with pytest.raises(ToolError):
        ApplyPatchTool().run(ctx, patch=patch)


def test_run_command_stores_full_output_and_returns_bounded(ctx):
    tool = RunCommandTool()
    out = tool.run(ctx, command=["python", "-c", "print('x' * 10)"])
    assert "xxxxxxxxxx" in out
    assert ctx.command_outputs  # full log kept outside the model context
    command_id = next(iter(ctx.command_outputs))
    assert "xxxxxxxxxx" in ReadCommandOutputTool().run(ctx, command_id=command_id)


def test_run_command_rejects_disallowed_binaries(ctx):
    with pytest.raises(ToolError):
        RunCommandTool().run(ctx, command=["curl", "https://example.com"])
    with pytest.raises(ToolError):
        RunCommandTool().run(ctx, command=["git", "push"])


def test_update_plan_tool_tracks_status():
    board = PlanBoard()
    out = UpdatePlanTool(board).run(
        ToolContext(repo_path="."),  # type: ignore[arg-type]
        steps=[
            {"step": "investigate", "status": "completed"},
            {"step": "patch", "status": "in_progress"},
        ],
    )
    assert "investigate" in out
    assert board.steps[1].status == "in_progress"


def test_registry_validates_tool_names(ctx):
    registry: ToolRegistry = default_registry(PlanBoard())
    assert {"read_file", "apply_patch", "run_command"} <= set(registry.tools)
    with pytest.raises(ToolError):
        registry.invoke(ctx, "no_such_tool", {})
    specs = registry.specs()
    assert all({"name", "description", "parameters"} <= set(spec) for spec in specs)
