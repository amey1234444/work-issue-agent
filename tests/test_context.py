from agent.config import Config
from agent.context import build_repo_context, read_files


def _make_repo(tmp_path):
    (tmp_path / "AGENTS.md").write_text("# rules\nUse python 3.10")
    (tmp_path / "README.md").write_text("# project")
    rules_dir = tmp_path / ".ai" / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "testing.md").write_text("write tests")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hi')")
    return tmp_path


def test_build_repo_context_collects_instructions_and_rules(tmp_path):
    repo = _make_repo(tmp_path)
    cfg = Config()
    ctx = build_repo_context(repo, cfg)
    assert "AGENTS.md" in ctx.instructions
    assert "README.md" in ctx.instructions
    assert "testing.md" in ctx.rules
    assert "src/main.py" in ctx.tree
    block = ctx.instructions_block()
    assert "rule: testing.md" in block


def test_read_files_skips_escapes(tmp_path):
    repo = _make_repo(tmp_path)
    result = read_files(repo, ["src/main.py", "../../etc/passwd"])
    assert "src/main.py" in result
    assert len(result) == 1
