---
title: Local execution and safety
description: Know the filesystem, shell, credential, and Git boundaries.
group: Operate and extend
order: 12
source: github_issue_agent/git_ops.py
---

The agent runs on your machine with your process permissions. Use a clean, disposable checkout for tasks and review the diff before merging.

## What dry run means

`--dry-run` stops after planning. It does not apply edits, execute verification commands, commit, push, or open a PR. It still reads repository context, makes real provider calls when selected, and fetches a GitHub issue when supplied.

To plan with no external API calls, use `--provider mock`, a prompt instead of an issue, and `--no-pr --dry-run`.

## What local mode means

`--no-pr` disables the branch/commit/push/PR sequence. It still applies model-generated file changes and executes verification commands. It is not a read-only mode.

## Filesystem guard

Selected file reads and file edits resolve the requested path and reject paths outside the repository root. That guard helps constrain file operations performed by those modules.

Verification commands run with `shell=True` and the user's permissions. They are not sandboxed and are not restricted by the file-edit path guard. Use trusted repositories and an isolated environment appropriate to the task.

## Git behavior

- The PR step stages **all** checkout changes with `git add -A`.
- Branch creation uses `git checkout -B`, which can reset an existing branch with the same name.
- `--base` changes the PR target; it does not synchronize the local checkout.
- File changes are not automatically rolled back after a failure.

Start from a clean checkout of the intended base. Avoid mixing personal edits with an agent run.

## Credential behavior

The current HTTPS push helper can embed the GitHub token in the `origin` remote URL. It does not restore that URL after pushing. Avoid printing or sharing credential-bearing remotes. After a run, restore the clean origin URL if needed:

```bash
git remote set-url origin https://github.com/OWNER/REPO.git
```

Replace the URL with your repository. Do not commit `.env` files or put API keys in examples. An explicit Python `api_key` is written to the process environment.

## Provider context

Real providers receive instructions, tasks, the tree, selected source files, and failure feedback. The mock provider avoids model API calls, but it does not disable GitHub actions on its own.

For a full record of known behavior, see [Verification and results](/docs/verification/) and the linked source files.
