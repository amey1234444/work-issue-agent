---
title: Model providers
description: Choose your model without changing your repository workflows.
group: Build with the agent
order: 5
source: github_issue_agent/llm.py
---

All four providers share the same planning and implementation interface. The agent asks for structured JSON; model quality and instruction clarity influence the resulting edits.

## Provider matrix

| Provider | Install extra | API key | Model setting |
| --- | --- | --- | --- |
| Anthropic | `[anthropic]` | `ANTHROPIC_API_KEY` | `ANTHROPIC_MODEL` |
| OpenAI | `[openai]` | `OPENAI_API_KEY` | `OPENAI_MODEL` |
| OpenRouter | `[openai]` | `OPENROUTER_API_KEY` | `OPENROUTER_MODEL` |
| Mock | None | None | Not applicable |

## Anthropic

```dotenv
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=replace-with-your-key
ANTHROPIC_MODEL=replace-with-an-available-model-id
```

Uses the Anthropic Messages SDK. The implementation requests a maximum of 8,192 output tokens and joins text blocks from the response.

## OpenAI

```dotenv
LLM_PROVIDER=openai
OPENAI_API_KEY=replace-with-your-key
OPENAI_MODEL=replace-with-an-available-model-id
```

Uses the OpenAI Chat Completions interface, with system and user messages and a maximum of 8,192 output tokens. Select a model compatible with that interface and its request parameters.

## OpenRouter

```dotenv
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=replace-with-your-key
OPENROUTER_MODEL=replace-with-an-available-model-slug
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
```

Reuses the OpenAI SDK against the configured base URL. When the URL contains `openrouter`, the request includes `reasoning: { enabled: false }`. Model availability, pricing, context limits, and rate limits are determined by your provider account. A `:free` suffix in a repository example does not guarantee current availability or unlimited use.

## Mock

```bash
github-issue-agent run work-issue \
  --prompt "Try the pipeline" --provider mock --no-pr
```

Returns a fixed plan and creates `AGENT_NOTES.md`. It does not solve the requested task. It needs no model key, but an issue URL or enabled PR creation still requires GitHub authentication. A true offline run uses a prompt and `--no-pr`.

## Override from Python

```python
import os
from github_issue_agent import run_workflow

result = run_workflow(
    "work-issue",
    prompt="Add a regression test for empty input",
    repo_path="./target-repo",
    provider="openai",
    api_key=os.environ["OPENAI_API_KEY"],
    model=os.environ["OPENAI_MODEL"],
    open_pr=False,
)
```

The API writes an explicitly supplied `api_key` into the provider's environment variable. Take that process-wide behavior into account when designing concurrent integrations.
