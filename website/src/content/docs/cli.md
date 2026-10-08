---
title: CLI reference
description: Every command, flag, and exit status in one place.
group: Reference
order: 8
source: github_issue_agent/cli.py
---

Use `github-issue-agent` or its alias `ai-agent`. Put run flags after the subcommand.

## List workflows

```bash
github-issue-agent list --path ./target-repo
```

Discovers `.ai/workflows/*.md` in the target repository. Each filename becomes the workflow name; the first non-empty line supplies its description. Returns exit code 1 if none are found.

## Resolve a GitHub issue

```bash
github-issue-agent work-issue \
  https://github.com/OWNER/REPO/issues/123 \
  --path ./target-repo --provider openai --no-pr
```

This is shorthand for `run work-issue --issue <url>`. The target must contain `.ai/workflows/work-issue.md`.

## Run a named workflow

```bash
github-issue-agent run add-feature \
  --prompt "Add a --json flag to the export command" \
  --path ./target-repo --no-pr
```

`run` accepts `--issue <url>`, `--prompt <text>`, or both. When both are present, the task combines the issue details with your prompt. At least one is required.

## Run options

| Flag | Default | Behavior |
| --- | --- | --- |
| `--path <directory>` | `.` | Target local checkout |
| `--provider <name>` | Resolved config | Override `anthropic`, `openai`, `openrouter`, or `mock` |
| `--dry-run` | Off | Build a plan, then stop before file edits |
| `--no-pr` | Off | Apply and verify locally; skip branch, commit, push, and PR |
| `--base <branch>` | GitHub default branch | Set the PR's base branch |

`--base` selects the PR base only; it does not check out or reset your local working tree to that branch. Start from the intended revision yourself.

There is no CLI `--model` or `--max-iterations` flag. Use the corresponding environment variables or Python API arguments.

## Plan without GitHub access

```bash
github-issue-agent run work-issue \
  --prompt "Describe the task" \
  --provider mock --dry-run --no-pr --path .
```

Both a prompt-only task and `--no-pr` are necessary to avoid the GitHub client. A real provider still makes model calls during planning.

## Global flags

```bash
github-issue-agent --version
github-issue-agent --help
github-issue-agent run --help
```

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Dry run completed, or the result reports `tests_passed=True` |
| `1` | Verification failed, or `list` found no workflows |
| `2` | CLI usage error or an `AgentError` handled by the CLI |

Some lower-level exceptions may propagate rather than being converted to `AgentError`. A zero exit code does not prove tests ran: skipped verification also reports success. Read the output and [verification behavior](/docs/verification/).
