---
title: Instructions and context
description: Give the agent the conventions and code context it needs.
group: Build with the agent
order: 7
source: github_issue_agent/context.py
---

## Default instruction files

The agent reads existing files in this order:

1. `AGENTS.md`
2. `.github/copilot-instructions.md`
3. `CLAUDE.md`
4. `README.md`
5. `CONTRIBUTING.md`

It then includes files matching `.ai/rules/*.md`, sorted by path. Configure either list or glob in `.ai/config.yaml`.

The files are concatenated into context. The program does not resolve contradictory policies mechanically; make your instructions consistent and explicit.

## Write useful instructions

```markdown
# Repository Instructions

- Use Python 3.10+ and typed public functions.
- Keep fixes focused on the requested behavior.
- Add a regression test for each bug fix.
- Run pytest -q and ruff check . before proposing a change.
- Do not hand-edit generated files.
- Explain behavior changes and verification in the PR.
```

For a different stack, state the actual language version, build tool, package manager, and verification commands. If a file has unusual constraints, spell them out in a focused rule file.

## How files enter context

First, the agent supplies instruction files, rules, and the file tree to the planner. The planner returns `files_to_read`. The implementation step loads those requested files and includes their content alongside the plan and task.

The tree prefers `git ls-files`, which means newly created untracked source files may be absent from the tree. If Git does not supply a usable list, the code falls back to a filesystem walk that skips common generated and dependency folders.

## Context limits

| Item | Current limit |
| --- | --- |
| File tree | 400 entries |
| Individual instruction or selected source file | 20,000 characters |
| Test-failure feedback sent to the next attempt | Last 6,000 characters |

These limits are implemented in code; they are not configuration fields. Large files and repositories may lose relevant context. Keep workflows focused and instructions concise.

## Information sent to your provider

A real provider receives the task, instruction files, rules, file tree, selected file contents, and relevant failure output. Keep secrets out of instruction files and source context. Review the selected provider's data handling terms for your environment.

File reads and edits resolve paths against the target repository and reject paths outside it. This path guard is not a sandbox for the shell commands used during verification. See [Local execution and safety](/docs/safety/).
