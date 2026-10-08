---
title: Architecture
description: Follow a task from repository context to pull request.
group: Reference
order: 10
source: github_issue_agent/workflow.py
---

The CLI and public Python API share the same local orchestration pipeline. Planning and implementation use the selected LLM provider; filesystem, command execution, and GitHub operations remain explicit Python modules.

## Module map

| Module | Responsibility |
| --- | --- |
| `cli.py` | Parse commands and flags, stream progress, return exit codes |
| `api.py` | Orchestrate the public workflow and produce `WorkflowResult` |
| `config.py` | Resolve environment, `.env`, and YAML settings |
| `context.py` | Collect instructions, rules, tree, and selected files |
| `workflow.py` | Build prompts, parse plans and implementations |
| `llm.py` | Anthropic, OpenAI, OpenRouter, and mock adapters |
| `editor.py` | Apply create, modify, and delete edits inside the repo |
| `runner.py` | Execute verification commands and capture output |
| `git_ops.py` | Branch, commit, push, and remote helpers |
| `github_client.py` | Read issues and create pull requests through GitHub REST |
| `models.py` | Internal task, plan, and edit dataclasses |
| `__init__.py` | Public exports and package version |

## Planning

`Agent.plan()` sends the workflow, repository instructions, file tree, and task to the model. The JSON response describes its understanding, selected files, and implementation steps.

## Implementation

`Agent.implement()` reloads the selected files and requests complete replacement contents for each edit, commands to verify them, and branch/commit/PR metadata. JSON extraction tolerates surrounding prose and fenced JSON, but malformed output can still fail.

## Verification loop

Each attempt applies the edits, runs the model's commands or the configured fallback, and captures output. On failure, the last 6,000 characters become feedback for the next implementation attempt. The original plan is reused rather than regenerated.

Attempts operate on the same working tree; there is no automatic rollback between them. The default is three total implementation attempts.

## Git and GitHub

When PR creation is enabled, the API checks for changes, reads `origin`, determines the PR base, creates the model-proposed branch, stages all changes, commits, pushes, and opens a PR.

Version 0.1.0 does not gate that sequence on `tests_passed`. It also uses `git checkout -B` for the proposed branch and `git add -A` for the commit. Start from a clean disposable checkout and review [execution boundaries](/docs/safety/).

## Extension points

- Add a Markdown workflow for a new task type.
- Change instruction files and rules for per-repository conventions.
- Replace planner/coder prompt files while preserving JSON contracts.
- Use the Python API as a building block for your own application.

A hosted service, multi-agent reviewer, background queue, and sandbox are possible future integrations, not capabilities shipped by this local package.
