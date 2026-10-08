---
title: Quickstart
description: Run your first workflow locally, then connect a real provider.
group: Start here
order: 2
source: github_issue_agent/api.py
---

Start with a disposable local checkout. The mock provider returns a deterministic plan and writes `AGENT_NOTES.md`, so you can understand the workflow before making model calls.

## 1. Install the package

You need Python 3.10 or newer and Git. These examples use a macOS or Linux shell; see [Installation](/docs/installation/) for Windows activation.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install github-issue-agent
```

## 2. Create a practice repository

```bash
mkdir agent-playground
cd agent-playground
git init
mkdir -p .ai/workflows
```

Create `.ai/workflows/work-issue.md` with:

```markdown
# Workflow: Work Issue

Read the task and repository instructions.
Plan a focused implementation.
Apply the required edits and add appropriate tests.
Run the repository's verification command.
Summarize the changes and the verification result.
```

Workflow files must exist in the **target repository**. Installing the Python package does not copy the source repository's `.ai/` directory into your project.

## 3. Preview the plan

```bash
github-issue-agent run work-issue \
  --prompt "Document the purpose of this practice repository" \
  --provider mock --no-pr --dry-run --path .
```

This combination needs neither an LLM key nor a GitHub token. It uses a prompt, does not request a PR, and stops before edits.

## 4. Apply the mock change

```bash
github-issue-agent run work-issue \
  --prompt "Document the purpose of this practice repository" \
  --provider mock --no-pr --path .
```

The mock provider creates `AGENT_NOTES.md`. Because this practice repository has no configured test command and the mock returns no commands, verification is skipped. The command demonstrates the wiring, not a real task-solving model.

## 5. Connect a real model

For OpenAI or OpenRouter, install the `openai` extra. For Anthropic, install the `anthropic` extra.

```bash
python -m pip install "github-issue-agent[openai]"
```

Create a `.env` file in the directory where you run the agent or in your target checkout:

```dotenv
LLM_PROVIDER=openai
OPENAI_API_KEY=replace-with-your-provider-key
OPENAI_MODEL=replace-with-an-available-model-id
GITHUB_TOKEN=replace-with-your-github-token
```

Keep `.env` out of Git. Use a model ID available to your provider account. See [Providers](/docs/providers/) for all options.

## 6. Work on a real issue

Have a clean local checkout of the repository that owns the issue, add `.ai/workflows/work-issue.md`, and configure its real test command in `.ai/config.yaml`.

```bash
github-issue-agent work-issue \
  https://github.com/OWNER/REPO/issues/123 \
  --path ./your-target-repo --dry-run
```

Replace the example URL and path. An issue URL requires a GitHub token even in dry-run mode. Remove `--dry-run` and add `--no-pr` to apply and test locally first. After reviewing the result, use a fresh clean checkout for a full PR-producing run.

## Next steps

- Set repository conventions in [Instructions and context](/docs/instructions/).
- Learn the behavior of every [CLI flag](/docs/cli/).
- Understand [verification results](/docs/verification/) before trusting a run.
