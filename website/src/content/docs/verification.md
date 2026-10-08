---
title: Verification and results
description: Understand retries, test output, and what success actually means.
group: Operate and extend
order: 11
source: github_issue_agent/api.py
---

## Choose an explicit test command

```yaml
# .ai/config.yaml
test_command: pytest -q
```

The model can supply one or more verification commands. Those commands take priority over this fallback. If neither source supplies a command, verification is skipped and `tests_passed` is set to true.

## Execution behavior

Commands run in the target repository through the local shell. Standard output and standard error are captured. Multiple commands run in order and stop at the first failure. Each command has a 1,800-second timeout; timeout results use exit code 124.

The runner treats exit code zero as success. It does not independently evaluate test coverage or whether a command actually tests the requested behavior.

## Retry behavior

The agent defaults to three total implementation attempts: the first implementation plus at most two corrections. Set `AGENT_MAX_ITERATIONS` or the API's `max_iterations` to a positive integer.

On failure, the last 6,000 characters of verification output are sent back to the model. Existing edits remain in the checkout. If all attempts fail, the result reports `tests_passed=False`.

## Important current behavior

**PR creation is not blocked by failed tests in version 0.1.0.** When PR creation is enabled, the API can still commit, push, and open a PR after exhausting the verification attempts. The CLI then exits with code 1 because the result reports failure.

Use `--no-pr` or `open_pr=False` when you need to inspect verification before any push. Use your repository's CI and branch protection to enforce checks on merge.

## Interpret the result

| Situation | `tests_passed` | What to inspect |
| --- | --- | --- |
| Dry run | `True` | Plan only; no implementation or verification happened |
| No commands configured or generated | `True` | Tests were skipped; check the progress event |
| Commands exit zero | `True` | Actual commands, output, coverage, and diff |
| Final attempt fails | `False` | Final output and full working-tree changes |

The result's `changed_files` and `test_output` describe the last attempt. Earlier edits may still exist. Inspect the full `git diff` and untracked files, not only the result fields.

## Review a local run

```bash
github-issue-agent work-issue \
  https://github.com/OWNER/REPO/issues/123 \
  --path ./target-repo --no-pr

git -C ./target-repo status --short
git -C ./target-repo diff
```

Run the real project checks yourself when needed, then decide which edits to commit. The agent does not provide a separate command for resuming a completed `--no-pr` run at just the PR step.
