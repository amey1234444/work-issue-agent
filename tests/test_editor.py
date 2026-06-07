import pytest

from agent.editor import EditError, apply_edits
from agent.models import FileEdit


def test_create_modify_delete(tmp_path):
    created = apply_edits(tmp_path, [FileEdit("a/b.txt", "create", "hello")])
    assert (tmp_path / "a" / "b.txt").read_text() == "hello"
    assert created == ["created a/b.txt"]

    modified = apply_edits(tmp_path, [FileEdit("a/b.txt", "modify", "bye")])
    assert (tmp_path / "a" / "b.txt").read_text() == "bye"
    assert modified == ["modified a/b.txt"]

    deleted = apply_edits(tmp_path, [FileEdit("a/b.txt", "delete")])
    assert not (tmp_path / "a" / "b.txt").exists()
    assert deleted == ["deleted a/b.txt"]


def test_path_escape_is_rejected(tmp_path):
    with pytest.raises(EditError):
        apply_edits(tmp_path, [FileEdit("../evil.txt", "create", "x")])
