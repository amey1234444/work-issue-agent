"""The continuous agent loop: tool execution, compaction and the completion gate."""

import subprocess

import pytest

from github_issue_agent.agent.completion_gate import check_completion, parse_final_report
from github_issue_agent.agent.loop import AgentLoop, AgentLoopError
from github_issue_agent.agent.state import ConversationState
from github_issue_agent.agent.text_protocol import TextProtocolProvider, parse_turn
from github_issue_agent.agent.types import AssistantTurn, Message, ToolCall
from github_issue_agent.repo_map import build_repo_map

FINAL = (
    "SUMMARY: Added a greeting helper.\n"
    "BRANCH: agent/greeting\n"
    "COMMIT: feat: add greeting helper\n"
    "PR_TITLE: Add greeting helper\n"
    "PR_BODY:\n"
    "Adds a helper and a test.\n"
    "VALIDATION: pytest -q\n"
)

PATCH = (
    "*** Begin Patch\n"
    "*** Add File: notes.md\n"
    "+written by the agent\n"
    "*** End Patch\n"
)


class ScriptedProvider:
    """Replays a fixed list of assistant turns."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = 0

    def converse(self, system, messages, tools):
        self.calls += 1
        return self.turns.pop(0) if self.turns else AssistantTurn(text=FINAL)


@pytest.fixture()
def git_repo(tmp_path):
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    for key, value in (("user.email", "a@b.c"), ("user.name", "agent")):
        subprocess.run(["git", "config", key, value], cwd=tmp_path, check=True)
    (tmp_path / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


def test_loop_runs_tools_then_returns_report(git_repo):
    provider = ScriptedProvider(
        [
            AssistantTurn(tool_calls=[ToolCall(id="1", name="read_file", arguments={"path": "app.py"})]),
            AssistantTurn(tool_calls=[ToolCall(id="2", name="apply_patch", arguments={"patch": PATCH})]),
            AssistantTurn(text=FINAL),
        ]
    )
    loop = AgentLoop(
        provider,
        repo_path=git_repo,
        system_prompt="be a good agent",
        require_validation=False,
    )
    result = loop.run("Please add notes.md")
    assert result.report.summary == "Added a greeting helper."
    assert result.report.branch == "agent/greeting"
    assert [call.split("(")[0] for call in result.tool_calls] == ["read_file", "apply_patch"]
    assert (git_repo / "notes.md").exists()
    assert result.validated


def test_loop_tool_errors_are_fed_back_not_raised(git_repo):
    provider = ScriptedProvider(
        [
            AssistantTurn(tool_calls=[ToolCall(id="1", name="read_file", arguments={"path": "nope"})]),
            AssistantTurn(tool_calls=[ToolCall(id="2", name="apply_patch", arguments={"patch": PATCH})]),
            AssistantTurn(text=FINAL),
        ]
    )
    loop = AgentLoop(
        provider, repo_path=git_repo, system_prompt="x", require_validation=False
    )
    result = loop.run("go")
    tool_messages = [m for m in loop.state.messages if m.role == "tool"]
    assert any("ERROR" in m.content for m in tool_messages)
    assert result.report.summary  # the run still completed


def test_gate_rejects_a_claim_without_changes(git_repo):
    provider = ScriptedProvider([AssistantTurn(text=FINAL)] * 6)
    loop = AgentLoop(
        provider, repo_path=git_repo, system_prompt="x", require_validation=False, max_steps=6
    )
    with pytest.raises(AgentLoopError):
        loop.run("go")
    # The gate told the model why it was rejected instead of silently accepting.
    feedback = [m.content for m in loop.state.messages if m.role == "user"]
    assert any("completion_gate" in text for text in feedback)
    assert any("no file changes" in text.lower() for text in feedback)


def test_loop_stops_at_max_steps(git_repo):
    looping = AssistantTurn(tool_calls=[ToolCall(id="1", name="list_files", arguments={})])
    provider = ScriptedProvider([looping] * 50)
    loop = AgentLoop(provider, repo_path=git_repo, system_prompt="x", max_steps=3)
    with pytest.raises(AgentLoopError):
        loop.run("go")


def test_parse_final_report_sanitises_branch():
    report = parse_final_report(FINAL.replace("agent/greeting", "Agent Greeting!!"))
    assert " " not in report.branch and report.branch


def test_check_completion_requires_validation():
    gate = check_completion(diff="+++ b/x.py\n+x\n", validation_runs=[], require_validation=True)
    assert not gate.passed
    assert "validation" in gate.as_feedback().lower()
    assert check_completion(
        diff="+++ b/x.py\n+x\n",
        validation_runs=[("pytest -q", True)],
        require_validation=True,
    ).passed


def test_check_completion_rejects_failing_validation_and_no_changes():
    assert not check_completion(
        diff="+++ b/x.py\n+x\n",
        validation_runs=[("pytest -q", False)],
        require_validation=True,
    ).passed
    assert not check_completion(diff="", validation_runs=[], require_validation=False).passed


def test_conversation_state_compacts_but_keeps_the_brief():
    state = ConversationState(compact_threshold=8, keep_recent=4)
    state.add(Message(role="user", content="THE ORIGINAL BRIEF"))
    for index in range(20):
        state.add(Message(role="assistant", content=f"step {index}"))
        state.add(Message(role="tool", content=f"result {index}", tool_call_id=str(index)))
        state.compact_if_needed()
    assert state.compactions > 0
    assert state.messages[0].content == "THE ORIGINAL BRIEF"
    assert len(state.messages) < 41
    assert "step 19" in state.messages[-2].content + state.messages[-1].content


def test_text_protocol_round_trip():
    turn = parse_turn('{"tool_calls": [{"name": "read_file", "arguments": {"path": "a.py"}}]}')
    assert turn.tool_calls[0].name == "read_file"
    assert parse_turn('{"final": "all done"}').text == "all done"
    # Prose around the JSON payload is tolerated.
    assert parse_turn('Sure!\n```json\n{"final": "done"}\n```').text == "done"


def test_text_protocol_provider_wraps_complete_only_providers(git_repo):
    class Legacy:
        def complete(self, system, user):
            return '{"final": "nothing to do"}'

    provider = TextProtocolProvider(Legacy())
    turn = provider.converse("sys", [Message(role="user", content="hi")], [])
    assert turn.text == "nothing to do"


def test_repo_map_indexes_symbols_and_frameworks(git_repo):
    (git_repo / "tests").mkdir()
    (git_repo / "tests" / "test_app.py").write_text("def test_add():\n    pass\n", encoding="utf-8")
    (git_repo / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    repo_map = build_repo_map(git_repo)
    assert "python" in repo_map.languages
    assert "pyproject.toml" in repo_map.build_files
    assert "pytest" in repo_map.test_frameworks
    entry = next(f for f in repo_map.files if f.path == "app.py")
    assert "def add" in entry.symbols
    block = repo_map.as_context_block()
    assert "app.py" in block
    # A map, not the source: file contents never appear.
    assert "return a + b" not in block
