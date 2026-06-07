"""Configuration loading: ``.env`` file, environment variables and ``.ai/config.yaml``."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


def load_dotenv(path: Path) -> None:
    """Load ``KEY=VALUE`` pairs from a .env file into os.environ.

    Existing environment variables are not overwritten. Lines starting with ``#``
    and blank lines are ignored. Values may be optionally quoted.
    """
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


# Default file names the agent treats as repository instructions, in priority order.
DEFAULT_INSTRUCTION_FILES = [
    "AGENTS.md",
    ".github/copilot-instructions.md",
    "CLAUDE.md",
    "README.md",
    "CONTRIBUTING.md",
]


@dataclass
class Config:
    """Resolved configuration for a single run."""

    provider: str = "anthropic"
    anthropic_model: str = "claude-3-5-sonnet-latest"
    openai_model: str = "gpt-4o"
    github_token: str | None = None
    max_iterations: int = 3
    instruction_files: list[str] = field(default_factory=lambda: list(DEFAULT_INSTRUCTION_FILES))
    rules_glob: str = ".ai/rules/*.md"
    test_command: str | None = None

    @classmethod
    def load(cls, repo_path: Path) -> Config:
        """Build a Config from .env, environment and the repo's ``.ai/config.yaml``."""
        load_dotenv(Path.cwd() / ".env")
        load_dotenv(repo_path / ".env")

        cfg = cls()
        cfg.provider = os.environ.get("LLM_PROVIDER", cfg.provider).lower()
        cfg.anthropic_model = os.environ.get("ANTHROPIC_MODEL", cfg.anthropic_model)
        cfg.openai_model = os.environ.get("OPENAI_MODEL", cfg.openai_model)
        cfg.github_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PAT")
        try:
            cfg.max_iterations = int(os.environ.get("AGENT_MAX_ITERATIONS", cfg.max_iterations))
        except ValueError:
            pass

        yaml_path = repo_path / ".ai" / "config.yaml"
        if yaml_path.exists():
            data = yaml.safe_load(yaml_path.read_text()) or {}
            if isinstance(data.get("instruction_files"), list):
                cfg.instruction_files = data["instruction_files"]
            if isinstance(data.get("rules_glob"), str):
                cfg.rules_glob = data["rules_glob"]
            if isinstance(data.get("test_command"), str):
                cfg.test_command = data["test_command"]
            if isinstance(data.get("provider"), str) and "LLM_PROVIDER" not in os.environ:
                cfg.provider = data["provider"].lower()
        return cfg
