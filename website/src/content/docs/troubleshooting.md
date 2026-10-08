---
title: Troubleshooting
description: Fix setup, workflow, provider, and verification problems.
group: Operate and extend
order: 13
---

## Command not found

Activate the Python environment where you installed the package, then reinstall with `python -m pip install github-issue-agent`. Check `github-issue-agent --version`. The import name is `github_issue_agent`, not `work_issue_agent`.

## Unknown workflow or no workflows found

Check `--path`. The agent searches the target repository's `.ai/workflows/` directory. A source-code install does not copy the example workflow files into another repository.

```bash
github-issue-agent list --path ./target-repo
```

Create or copy `.ai/workflows/work-issue.md` there before using `work-issue`.

## A GitHub token is required

Set `GITHUB_TOKEN` or `GITHUB_PAT`. Issue retrieval requires it even with `--dry-run` or `--no-pr`. For a token-free mock run, use a prompt and disable PR creation:

```bash
github-issue-agent run work-issue \
  --prompt "Try a local run" --provider mock --no-pr
```

## Provider package is not installed

```bash
python -m pip install "github-issue-agent[openai]"
python -m pip install "github-issue-agent[anthropic]"
```

OpenRouter uses the `openai` extra. Confirm the matching API key variable exists in the active environment or `.env`.

## Model not found, authentication errors, or 429 responses

Verify the key, model ID, account access, and provider quota. The repository's model defaults may no longer be available. Rate limits and model access are provider-specific. Select a supported model in the relevant environment variable or the API's `model` argument.

The implementation retry loop handles failed verification; it is not a general retry mechanism for every provider or network error.

## Invalid JSON or incomplete implementation

The planner and coder require structured JSON. Use a model capable of following that contract, keep the task focused, and avoid overriding system prompts without preserving the expected schema. Large complete-file responses can exceed output limits.

## Tests do not run

Set the target repo's `test_command` in `.ai/config.yaml`. The agent skips verification when the model returns no commands and there is no configured fallback. `tests_passed=True` alone does not prove tests ran.

## Tests keep failing

Read the captured command and output, verify the toolchain is installed, and tighten acceptance criteria and repository rules. The final result reflects the last attempt; inspect the entire working tree for edits from earlier attempts.

## No file changes to commit

The PR step aborts if Git reports no changes. Check whether the requested edits already exist, the model produced no edits, or you ran a deterministic mock workflow twice.

## Cannot push or open a PR

Check repository access, `origin`, Git author configuration, and branch restrictions. The intended base must exist on GitHub. A push can succeed before PR creation fails, so inspect repository state before retrying.

## Report a reproducible issue

Open a [GitHub issue](https://github.com/amey1234444/work-issue-agent/issues/new) with the package version, provider/model, sanitized command, relevant workflow, and error output. Remove API keys, credential-bearing remote URLs, and private source content.
