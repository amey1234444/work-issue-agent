import os
import stat

import pytest

from github_issue_agent.editor import EditError, apply_edits, merge_changes
from github_issue_agent.models import FileEdit
from github_issue_agent.paths import PathPolicy, PathPolicyError


def test_create_modify_delete(tmp_path):
    created = apply_edits(tmp_path, [FileEdit("a/b.txt", "create", "hello")])
    assert (tmp_path / "a" / "b.txt").read_text() == "hello"
    assert [c.describe() for c in created] == ["created a/b.txt"]
    assert created[0].old_hash is None and created[0].new_hash

    modified = apply_edits(tmp_path, [FileEdit("a/b.txt", "modify", "bye")])
    assert (tmp_path / "a" / "b.txt").read_text() == "bye"
    assert [c.describe() for c in modified] == ["modified a/b.txt"]
    assert modified[0].old_hash == created[0].new_hash

    deleted = apply_edits(tmp_path, [FileEdit("a/b.txt", "delete")])
    assert not (tmp_path / "a" / "b.txt").exists()
    assert [c.describe() for c in deleted] == ["deleted a/b.txt"]
    assert deleted[0].new_hash is None


def test_path_escape_is_rejected(tmp_path):
    with pytest.raises(EditError):
        apply_edits(tmp_path, [FileEdit("../evil.txt", "create", "x")])
    with pytest.raises(EditError):
        apply_edits(tmp_path, [FileEdit("/etc/passwd", "modify", "x")])


def test_strict_create_modify_semantics(tmp_path):
    (tmp_path / "exists.txt").write_text("x")
    with pytest.raises(EditError, match="already exists"):
        apply_edits(tmp_path, [FileEdit("exists.txt", "create", "y")])
    with pytest.raises(EditError, match="does not exist"):
        apply_edits(tmp_path, [FileEdit("missing.txt", "modify", "y")])
    with pytest.raises(EditError, match="does not exist"):
        apply_edits(tmp_path, [FileEdit("missing.txt", "delete")])
    with pytest.raises(EditError, match="Unknown edit action"):
        apply_edits(tmp_path, [FileEdit("exists.txt", "rename", "y")])  # type: ignore[arg-type]
    with pytest.raises(EditError, match="twice"):
        apply_edits(tmp_path, [FileEdit("n.txt", "create", "1"), FileEdit("n.txt", "create", "2")])
    assert (tmp_path / "exists.txt").read_text() == "x"


def test_transaction_rolls_back_bytes_and_mode_on_failure(tmp_path):
    keep = tmp_path / "keep.sh"
    keep.write_bytes(b"#!/bin/sh\necho hi\n")
    keep.chmod(0o755)
    original_mode = stat.S_IMODE(keep.stat().st_mode)

    # Second edit fails validation-independent: make the target dir unwritable so the write errors.
    blocked_dir = tmp_path / "ro"
    blocked_dir.mkdir()
    (blocked_dir / "file.txt").write_text("orig")
    blocked_dir.chmod(0o555)
    if os.access(blocked_dir / "file.txt", os.W_OK) and os.geteuid() == 0:
        pytest.skip("running as root; permission-based failure cannot be simulated")
    try:
        with pytest.raises(EditError):
            apply_edits(
                tmp_path,
                [
                    FileEdit("keep.sh", "modify", "#!/bin/sh\necho changed\n"),
                    FileEdit("new/dir/created.txt", "create", "n"),
                    FileEdit("ro/file.txt", "modify", "changed"),
                ],
            )
    finally:
        blocked_dir.chmod(0o755)

    assert keep.read_bytes() == b"#!/bin/sh\necho hi\n"
    assert stat.S_IMODE(keep.stat().st_mode) == original_mode
    assert (blocked_dir / "file.txt").read_text() == "orig"
    assert not (tmp_path / "new").exists(), "directories created by the failed transaction are removed"


def test_no_partial_writes_when_later_edit_invalid(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    with pytest.raises(EditError):
        apply_edits(tmp_path, [FileEdit("a.txt", "modify", "changed"), FileEdit("../x", "create", "x")])
    assert (tmp_path / "a.txt").read_text() == "a"


def test_symlink_escape_is_rejected(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("s")
    (tmp_path / "link").symlink_to(outside, target_is_directory=True)
    (tmp_path / "flink").symlink_to(outside / "secret.txt")
    with pytest.raises(EditError, match="outside"):
        apply_edits(tmp_path, [FileEdit("link/secret.txt", "modify", "x")])
    with pytest.raises(EditError, match="outside"):
        apply_edits(tmp_path, [FileEdit("flink", "modify", "x")])
    assert (outside / "secret.txt").read_text() == "s"


def test_protected_paths_are_rejected(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("[core]")
    (tmp_path / ".env").write_text("TOKEN=1")
    for rel in (".git/config", ".env", "deploy/key.pem", "config/.env.prod", "svc/credentials.json"):
        with pytest.raises(EditError, match="protected"):
            apply_edits(tmp_path, [FileEdit(rel, "create" if not (tmp_path / rel).exists() else "modify", "x")])
    assert (tmp_path / ".env").read_text() == "TOKEN=1"


def test_policy_check_and_custom_patterns(tmp_path):
    policy = PathPolicy(tmp_path, protected=("secrets/**",))
    assert policy.check("src/app.py")
    assert not policy.check("secrets/db.yaml")
    assert not policy.check("../up")
    with pytest.raises(PathPolicyError):
        policy.resolve("")


def test_merge_changes_preserves_full_manifest():
    from github_issue_agent.editor import FileChange

    first = [FileChange("a.py", "created", None, "h1"), FileChange("b.py", "modified", "h0", "h2")]
    second = [FileChange("a.py", "modified", "h1", "h3"), FileChange("c.py", "created", None, "h4")]
    merged = merge_changes(first, second)
    by_path = {c.path: c for c in merged}
    assert set(by_path) == {"a.py", "b.py", "c.py"}
    assert by_path["a.py"].action == "created"  # created in this run, still a new file overall
    assert by_path["a.py"].old_hash is None and by_path["a.py"].new_hash == "h3"
    # create then delete of a brand-new file cancels out
    gone = merge_changes([FileChange("t.py", "created", None, "h")], [FileChange("t.py", "deleted", "h", None)])
    assert gone == []
