import sys
import types

import pytest

from agent import llm
from agent.config import Config


class _FakeOpenAI:
    """Records the kwargs the provider passes to the OpenAI client."""

    instances: list["_FakeOpenAI"] = []

    def __init__(self, api_key=None, base_url=None):
        self.api_key = api_key
        self.base_url = base_url
        _FakeOpenAI.instances.append(self)


@pytest.fixture
def fake_openai(monkeypatch):
    _FakeOpenAI.instances.clear()
    module = types.ModuleType("openai")
    module.OpenAI = _FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", module)
    return _FakeOpenAI


def test_get_provider_openrouter(monkeypatch, fake_openai):
    monkeypatch.setenv("OPENROUTER_API_KEY", "router-key")
    cfg = Config(
        provider="openrouter",
        openrouter_model="vendor/model:free",
        openrouter_base_url="https://openrouter.ai/api/v1",
    )
    provider = llm.get_provider(cfg)
    assert isinstance(provider, llm.OpenAIProvider)
    client = fake_openai.instances[-1]
    assert client.api_key == "router-key"
    assert client.base_url == "https://openrouter.ai/api/v1"


def test_openai_provider_uses_api_key_env_and_base_url(monkeypatch, fake_openai):
    monkeypatch.setenv("OPENROUTER_API_KEY", "router-key")
    llm.OpenAIProvider(
        "vendor/model:free",
        api_key_env="OPENROUTER_API_KEY",
        base_url="https://example.test/v1",
    )
    client = fake_openai.instances[-1]
    assert client.api_key == "router-key"
    assert client.base_url == "https://example.test/v1"


def test_openai_provider_defaults_to_openai_key(monkeypatch, fake_openai):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    llm.OpenAIProvider("gpt-4o")
    client = fake_openai.instances[-1]
    assert client.api_key == "openai-key"
    assert client.base_url is None


def test_missing_api_key_raises(monkeypatch, fake_openai):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(llm.LLMError):
        llm.OpenAIProvider("m", api_key_env="OPENROUTER_API_KEY")


def test_unknown_provider_raises():
    with pytest.raises(llm.LLMError):
        llm.get_provider(Config(provider="bogus"))


def test_config_load_reads_openrouter_env(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_MODEL", "vendor/model:free")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://custom.example/api")
    cfg = Config.load(tmp_path)
    assert cfg.openrouter_model == "vendor/model:free"
    assert cfg.openrouter_base_url == "https://custom.example/api"
