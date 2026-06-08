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
