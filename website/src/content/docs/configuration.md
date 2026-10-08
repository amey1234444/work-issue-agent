---
title: Configuration
description: Environment variables, repository configuration, and override behavior.
group: Build with the agent
order: 4
source: github_issue_agent/config.py
---

Configuration comes from environment variables, `.env` files, `.ai/config.yaml`, and explicit Python API arguments.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `LLM_PROVIDER` | `anthropic` | `anthropic`, `openai`, `openrouter`, or `mock` |
| `ANTHROPIC_API_KEY` | Unset | Anthropic SDK key |
| `ANTHROPIC_MODEL` | `claude-3-5-sonnet-latest` | Anthropic model ID |
| `OPENAI_API_KEY` | Unset | OpenAI SDK key |
| `OPENAI_MODEL` | `gpt-4o` | OpenAI model ID |
| `OPENROUTER_API_KEY` | Unset | OpenRouter API key |
| `OPENROUTER_MODEL` | `openai/gpt-oss-120b:free` | OpenRouter model slug |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | OpenRouter-compatible endpoint |
| `GITHUB_TOKEN` | Unset | GitHub API and push authentication |
| `GITHUB_PAT` | Unset | Fallback when `GITHUB_TOKEN` is absent |
| `AGENT_MAX_ITERATIONS` | `3` | Total implementation attempts, including the first |

These are defaults in the checked-in version 0.1.0 code, not promises that those model IDs remain available. Set a model currently offered by your provider.

## Loading order

1. Existing process environment variables are preserved.
2. `.env` in the current working directory fills missing variables.
3. `.env` in the target repository fills variables still missing.
4. `.ai/config.yaml` supplies repository settings. Its `provider` is used only if `LLM_PROVIDER` is absent.
5. Explicit Python API overrides take precedence for supported arguments. The CLI's `--provider` overrides provider selection for that run.

The `.env` loader accepts `KEY=VALUE`, optional quotes, comments starting with `#`, and blank lines. It is a small loader, so use literal values rather than shell expansion expressions.

## Repository settings

```yaml
# .ai/config.yaml
provider: openai
instruction_files:
  - AGENTS.md
  - .github/copilot-instructions.md
  - CLAUDE.md
  - README.md
  - CONTRIBUTING.md
rules_glob: .ai/rules/*.md
test_command: pytest -q
```

These four fields are the settings read from YAML. A configured `instruction_files` list replaces the default list. The test command is a fallback: commands returned by the model take priority.

## Configure credentials locally

```dotenv
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=replace-with-your-provider-key
OPENROUTER_MODEL=replace-with-an-available-model-slug
GITHUB_TOKEN=replace-with-your-github-token
AGENT_MAX_ITERATIONS=3
```

Use a positive integer for `AGENT_MAX_ITERATIONS`. A non-integer environment value falls back to the default; zero or a negative value leads to no implementation and an error.

## GitHub authentication

The current client expects a token whenever an issue URL is provided or PR creation is enabled. The repository documents a classic personal access token with `repo` scope. It must have access to the target repository.

A prompt-only run with `--no-pr` avoids the GitHub client. `--dry-run` by itself does not bypass GitHub authentication. Review [Local execution and safety](/docs/safety/) before using a credentialed checkout.
