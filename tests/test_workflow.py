from github_issue_agent.workflow import extract_json


def test_extract_json_plain():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_with_code_fence():
    text = "Here you go:\n```json\n{\"branch\": \"x\", \"edits\": []}\n```\nthanks"
    assert extract_json(text) == {"branch": "x", "edits": []}


def test_extract_json_nested_braces():
    text = 'prefix {"outer": {"inner": [1, 2]}, "k": "v"} suffix'
    assert extract_json(text) == {"outer": {"inner": [1, 2]}, "k": "v"}


def test_extract_json_no_object_raises():
    import pytest

    with pytest.raises(ValueError):
        extract_json("no json here")


def test_extract_json_braces_inside_strings():
    text = 'noise {"content": "if (x) { return \\"}\\"; }", "n": 1} tail'
    assert extract_json(text) == {"content": 'if (x) { return "}"; }', "n": 1}


def test_extract_json_skips_leading_garbage_object_like_text():
    text = "Example: {not json} then {\"ok\": true}"
    assert extract_json(text) == {"ok": True}


def test_extract_json_empty_raises_model_output_error():
    import pytest

    from github_issue_agent.workflow import ModelOutputError

    with pytest.raises(ModelOutputError):
        extract_json("   ")


def test_parse_implementation_rejects_bad_shapes():
    import pytest

    from github_issue_agent.workflow import ModelOutputError, parse_implementation

    with pytest.raises(ModelOutputError, match="action"):
        parse_implementation({"edits": [{"path": "a", "action": "rename", "content": ""}]})
    with pytest.raises(ModelOutputError, match="path"):
        parse_implementation({"edits": [{"action": "create", "content": ""}]})
    with pytest.raises(ModelOutputError, match="missing 'content'"):
        parse_implementation({"edits": [{"path": "a", "action": "create"}]})
    with pytest.raises(ModelOutputError, match="commands"):
        parse_implementation({"edits": [], "commands": "pytest"})
    with pytest.raises(ModelOutputError, match="branch"):
        parse_implementation({"edits": [], "branch": 3})
    with pytest.raises(ModelOutputError, match="edits"):
        parse_implementation({"edits": {"path": "a"}})


def test_parse_implementation_defaults_and_delete():
    from github_issue_agent.workflow import parse_implementation

    impl = parse_implementation({"edits": [{"path": "a", "action": "delete"}], "branch": None})
    assert impl.branch == "agent/change"
    assert impl.edits[0].action == "delete" and impl.edits[0].content == ""
    assert impl.commands == []


def test_parse_plan_rejects_non_string_lists():
    import pytest

    from github_issue_agent.workflow import ModelOutputError, parse_plan

    with pytest.raises(ModelOutputError):
        parse_plan({"files_to_read": [1, 2]})
    assert parse_plan({"understanding": "u", "steps": None}).steps == []
