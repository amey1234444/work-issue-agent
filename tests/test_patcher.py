"""Tests for the apply_patch envelope parser and atomic applier."""

import pytest

from github_issue_agent.patcher import PatchError, apply_patch, parse_patch

BASE = "line one\nline two\nline three\n"


def test_parse_patch_reads_all_actions():
    ops = parse_patch(
        "*** Begin Patch\n"
        "*** Add File: a.txt\n"
        "+hello\n"
        "*** Delete File: b.txt\n"
        "*** Update File: c.txt\n"
        "@@\n"
        " keep\n"
        "-drop\n"
        "+add\n"
        "*** End Patch\n"
    )
    assert [(op.action, op.path) for op in ops] == [
        ("add", "a.txt"),
        ("delete", "b.txt"),
        ("update", "c.txt"),
    ]
    assert ops[2].hunks[0].old_lines == ["keep", "drop"]
    assert ops[2].hunks[0].new_lines == ["keep", "add"]


def test_parse_patch_requires_envelope():
    with pytest.raises(PatchError):
        parse_patch("*** Update File: x\n@@\n+y\n")


def test_apply_patch_add_update_delete(tmp_path):
    (tmp_path / "c.txt").write_text(BASE, encoding="utf-8")
    (tmp_path / "b.txt").write_text("bye\n", encoding="utf-8")
    changed = apply_patch(
        tmp_path,
        "*** Begin Patch\n"
        "*** Add File: a.txt\n"
        "+hello\n"
        "*** Delete File: b.txt\n"
        "*** Update File: c.txt\n"
        "@@\n"
        " line one\n"
        "-line two\n"
        "+line 2\n"
        " line three\n"
        "*** End Patch\n",
    )
    assert sorted(changed) == ["created a.txt", "deleted b.txt", "modified c.txt"]
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "hello\n"
    assert not (tmp_path / "b.txt").exists()
    assert (tmp_path / "c.txt").read_text(encoding="utf-8") == "line one\nline 2\nline three\n"


def test_apply_patch_is_atomic(tmp_path):
    (tmp_path / "c.txt").write_text(BASE, encoding="utf-8")
    with pytest.raises(PatchError):
        apply_patch(
            tmp_path,
            "*** Begin Patch\n"
            "*** Update File: c.txt\n"
            "@@\n"
            " line one\n"
            "-line two\n"
            "+line 2\n"
            "*** Update File: missing.txt\n"
            "@@\n"
            " nope\n"
            "+x\n"
            "*** End Patch\n",
        )
    # The first (valid) hunk must have been rolled back.
    assert (tmp_path / "c.txt").read_text(encoding="utf-8") == BASE


def test_apply_patch_rejects_paths_outside_repo(tmp_path):
    with pytest.raises(PatchError):
        apply_patch(tmp_path, "*** Begin Patch\n*** Add File: ../evil.txt\n+x\n*** End Patch\n")


def test_apply_patch_rejects_missing_context(tmp_path):
    (tmp_path / "c.txt").write_text(BASE, encoding="utf-8")
    with pytest.raises(PatchError):
        apply_patch(
            tmp_path,
            "*** Begin Patch\n*** Update File: c.txt\n@@\n not present\n+x\n*** End Patch\n",
        )
