import pytest


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch):
    """Tests must not depend on credentials present in the developer's shell."""
    for name in (
        "GITHUB_TOKEN",
        "GITHUB_PAT",
        "GH_TOKEN",
        "LLM_PROVIDER",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY",
        "AGENT_MAX_ITERATIONS",
    ):
        monkeypatch.delenv(name, raising=False)
