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
    openrouter_model: str = "openai/gpt-oss-120b:free"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    github_token: str | None = None
    max_iterations: int = 3
    instruction_files: list[str] = field(default_factory=lambda: list(DEFAULT_INSTRUCTION_FILES))
    rules_glob: str = ".ai/rules/*.md"
    test_command: str | None = None
    #: "agent" runs the Codex-style tool loop; "workflow" the legacy plan/implement pass.
    mode: str = "agent"
    #: Tool calls one agent run may make before giving up.
    max_steps: int = 60
    #: Commands run to validate a change (and a merge resolution).
    validation_commands: list[str] = field(default_factory=list)
    #: Extra executables the agent may call, on top of the built-in allowlist.
    allowed_commands: list[str] = field(default_factory=list)
    #: Resolve conflicts with the base branch before opening a PR.
    auto_resolve_conflicts: bool = True
    #: Forced conflict side ("ours"/"theirs"), or None to decide per hunk.
    conflict_preference: str | None = None

    @classmethod
    def load(cls, repo_path: Path) -> Config:
        """Build a Config from .env, environment and the repo's ``.ai/config.yaml``."""
        load_dotenv(Path.cwd() / ".env")
        load_dotenv(repo_path / ".env")

        cfg = cls()
        cfg.provider = os.environ.get("LLM_PROVIDER", cfg.provider).lower()
        cfg.anthropic_model = os.environ.get("ANTHROPIC_MODEL", cfg.anthropic_model)
        cfg.openai_model = os.environ.get("OPENAI_MODEL", cfg.openai_model)
        cfg.openrouter_model = os.environ.get("OPENROUTER_MODEL", cfg.openrouter_model)
        cfg.openrouter_base_url = os.environ.get("OPENROUTER_BASE_URL", cfg.openrouter_base_url)
        cfg.github_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PAT")
        cfg.mode = os.environ.get("AGENT_MODE", cfg.mode).lower()
        for attribute, env_var in (("max_iterations", "AGENT_MAX_ITERATIONS"), ("max_steps", "AGENT_MAX_STEPS")):
            try:
                setattr(cfg, attribute, int(os.environ.get(env_var, getattr(cfg, attribute))))
            except ValueError:
                pass
        if os.environ.get("AGENT_AUTO_RESOLVE_CONFLICTS"):
            cfg.auto_resolve_conflicts = os.environ["AGENT_AUTO_RESOLVE_CONFLICTS"].lower() not in {
                "0",
                "false",
                "no",
            }

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
            if isinstance(data.get("mode"), str) and "AGENT_MODE" not in os.environ:
                cfg.mode = data["mode"].lower()
            for key in ("validation_commands", "allowed_commands"):
                if isinstance(data.get(key), list):
                    setattr(cfg, key, [str(item) for item in data[key]])
            if isinstance(data.get("max_steps"), int) and "AGENT_MAX_STEPS" not in os.environ:
                cfg.max_steps = data["max_steps"]
            if isinstance(data.get("auto_resolve_conflicts"), bool):
                cfg.auto_resolve_conflicts = data["auto_resolve_conflicts"]
            if isinstance(data.get("conflict_preference"), str):
                cfg.conflict_preference = data["conflict_preference"].lower()

        if not cfg.validation_commands and cfg.test_command:
            cfg.validation_commands = [cfg.test_command]
        return cfg
