"""Configuration loading: ``.env`` file, environment variables and ``.ai/config.yaml``.

Configuration is validated (types, ranges, allowed values) before the agent
touches any file so a malformed setting fails fast with a ``configuration``
error rather than mid-run.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .paths import DEFAULT_PROTECTED_PATTERNS

VALID_PROVIDERS = ("anthropic", "openai", "openrouter", "mock")


class ConfigError(ValueError):
    """Configuration is malformed or out of range."""


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

# Environment variable each provider's SDK reads its key from.
PROVIDER_API_KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


@dataclass
class Config:
    """Resolved configuration for a single run.

    Credentials (``api_key``, ``github_token``) are carried on the instance and
    never written back into ``os.environ`` so concurrent runs cannot interfere.
    """

    provider: str = "anthropic"
    anthropic_model: str = "claude-3-5-sonnet-latest"
    openai_model: str = "gpt-4o"
    openrouter_model: str = "openai/gpt-oss-120b:free"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    api_key: str | None = None
    github_token: str | None = None
    max_iterations: int = 3
    deadline_seconds: int = 3600
    command_timeout: int = 1800
    max_output_chars: int = 200_000
    instruction_files: list[str] = field(default_factory=lambda: list(DEFAULT_INSTRUCTION_FILES))
    rules_glob: str = ".ai/rules/*.md"
    test_command: str | None = None
    # Required checks that always run on the final tree (in addition to
    # ``test_command``). The model may add commands but can never remove these.
    checks: list[str] = field(default_factory=list)
    # If True (default) a run whose required checks did not all pass cannot
    # publish a PR. Set to False only for repos that genuinely have no checks.
    require_validation: bool = True
    draft_pr: bool = True
    protected_paths: list[str] = field(default_factory=lambda: list(DEFAULT_PROTECTED_PATTERNS))
    protected_branches: list[str] = field(
        default_factory=lambda: ["main", "master", "develop", "release"]
    )

    @property
    def model(self) -> str:
        if self.provider == "anthropic":
            return self.anthropic_model
        if self.provider == "openai":
            return self.openai_model
        if self.provider == "openrouter":
            return self.openrouter_model
        return "mock"

    @property
    def required_checks(self) -> list[str]:
        cmds: list[str] = []
        if self.test_command:
            cmds.append(self.test_command)
        for c in self.checks:
            if c not in cmds:
                cmds.append(c)
        return cmds

    def resolve_api_key(self) -> str | None:
        if self.api_key:
            return self.api_key
        env_var = PROVIDER_API_KEY_ENV.get(self.provider)
        return os.environ.get(env_var) if env_var else None

    def validate(self) -> None:
        if self.provider not in VALID_PROVIDERS:
            raise ConfigError(
                f"Unknown provider {self.provider!r} (expected one of {', '.join(VALID_PROVIDERS)})"
            )
        if self.max_iterations < 1:
            raise ConfigError("max_iterations must be >= 1")
        if self.deadline_seconds < 1:
            raise ConfigError("deadline_seconds must be >= 1")
        if self.command_timeout < 1:
            raise ConfigError("command_timeout must be >= 1")
        if self.max_output_chars < 1000:
            raise ConfigError("max_output_chars must be >= 1000")
        if not isinstance(self.instruction_files, list) or not all(
            isinstance(x, str) for x in self.instruction_files
        ):
            raise ConfigError("instruction_files must be a list of strings")
        for name, value in (("checks", self.checks), ("protected_paths", self.protected_paths)):
            if not isinstance(value, list) or not all(isinstance(x, str) and x for x in value):
                raise ConfigError(f"{name} must be a list of non-empty strings")

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
        cfg.max_iterations = _env_int("AGENT_MAX_ITERATIONS", cfg.max_iterations)
        cfg.deadline_seconds = _env_int("AGENT_DEADLINE_SECONDS", cfg.deadline_seconds)
        cfg.command_timeout = _env_int("AGENT_COMMAND_TIMEOUT", cfg.command_timeout)

        yaml_path = repo_path / ".ai" / "config.yaml"
        if yaml_path.exists():
            try:
                data = yaml.safe_load(yaml_path.read_text()) or {}
            except yaml.YAMLError as exc:
                raise ConfigError(f"Invalid YAML in {yaml_path}: {exc}") from exc
            if not isinstance(data, dict):
                raise ConfigError(f"{yaml_path} must contain a mapping")
            cfg._apply_yaml(data)
        cfg.validate()
        return cfg

    def _apply_yaml(self, data: dict) -> None:
        def _typed(key: str, kind: type) -> object | None:
            if key not in data or data[key] is None:
                return None
            value = data[key]
            if kind is int and isinstance(value, bool):
                raise ConfigError(f"{key} must be an integer")
            if not isinstance(value, kind):
                raise ConfigError(f"{key} must be of type {kind.__name__}")
            return value

        if (v := _typed("instruction_files", list)) is not None:
            self.instruction_files = list(v)  # type: ignore[call-overload]
        if (v := _typed("rules_glob", str)) is not None:
            self.rules_glob = str(v)
        if (v := _typed("test_command", str)) is not None:
            self.test_command = str(v)
        if (v := _typed("checks", list)) is not None:
            self.checks = list(v)  # type: ignore[call-overload]
        if (v := _typed("provider", str)) is not None and "LLM_PROVIDER" not in os.environ:
            self.provider = str(v).lower()
        if (v := _typed("max_iterations", int)) is not None and "AGENT_MAX_ITERATIONS" not in os.environ:
            self.max_iterations = int(v)  # type: ignore[call-overload]
        if (v := _typed("deadline_seconds", int)) is not None:
            self.deadline_seconds = int(v)  # type: ignore[call-overload]
        if (v := _typed("command_timeout", int)) is not None:
            self.command_timeout = int(v)  # type: ignore[call-overload]
        if (v := _typed("require_validation", bool)) is not None:
            self.require_validation = bool(v)
        if (v := _typed("draft_pr", bool)) is not None:
            self.draft_pr = bool(v)
        if (v := _typed("protected_paths", list)) is not None:
            self.protected_paths = list(DEFAULT_PROTECTED_PATTERNS) + list(v)  # type: ignore[call-overload]
        if (v := _typed("protected_branches", list)) is not None:
            self.protected_branches = list(v)  # type: ignore[call-overload]
