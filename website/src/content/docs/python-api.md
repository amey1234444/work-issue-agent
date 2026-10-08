---
title: Python API
description: Run workflows from scripts, services, and notebooks.
group: Reference
order: 9
source: github_issue_agent/api.py
---

Import the public API from `github_issue_agent`. Calls are synchronous and return a `WorkflowResult`.

## Resolve an issue

```python
from github_issue_agent import work_issue

result = work_issue(
    "https://github.com/OWNER/REPO/issues/123",
    repo_path="./target-repo",
    provider="openai",
    open_pr=False,
)

print(result.summary)
print(result.test_output)
print(result.changed_files)
```

Credentials fall back to the resolved environment configuration. `work_issue(url, **kwargs)` is shorthand for `run_workflow("work-issue", issue_url=url, **kwargs)`.

## Run a workflow

```python
from github_issue_agent import AgentError, run_workflow

def report(kind: str, message: str) -> None:
    print(f"[{kind}] {message}")

try:
    result = run_workflow(
        "fix-bug",
        prompt="Handle an empty input list without raising an exception",
        repo_path="./target-repo",
        provider="openai",
        max_iterations=3,
        open_pr=False,
        on_event=report,
    )
except AgentError as exc:
    print(f"Agent could not complete the run: {exc}")
else:
    print(result.tests_passed, result.test_output)
```

`AgentError` covers errors explicitly wrapped by the API. Provider, Git, file-edit, parsing, and network exceptions can also propagate; integrations should handle failures at their own application boundary.

## Parameters

All parameters after `workflow` are keyword-only on `run_workflow`.

| Parameter | Default | Description |
| --- | --- | --- |
| `workflow` | `"work-issue"` | Filename stem under `.ai/workflows/` |
| `repo_path` | `"."` | Target path as a string or `Path` |
| `issue_url` | `None` | GitHub issue to fetch |
| `prompt` | `None` | Free-form task; combined with issue if both provided |
| `provider` | `None` | Override configured provider |
| `api_key` | `None` | Override provider key through the process environment |
| `model` | `None` | Override selected provider's model |
| `github_token` | `None` | Override GitHub token |
| `base` | `None` | PR base; defaults to repository's default branch |
| `max_iterations` | `None` | Override total implementation attempts |
| `open_pr` | `True` | Enable branch, commit, push, and PR |
| `dry_run` | `False` | Plan only |
| `on_event` | `None` | Callback accepting `(kind, message)` |

Provide an issue URL, a prompt, or both. The named workflow must exist in the target repo.

## WorkflowResult

| Field | Type | Meaning |
| --- | --- | --- |
| `workflow` | `str` | Workflow that ran |
| `tests_passed` | `bool` | Last verification outcome; also true for dry runs and skipped tests |
| `summary` | `str` | Final implementation summary; empty for a dry run |
| `plan` | `str` | Human-readable plan |
| `changed_files` | `list[str]` | Human-readable edit descriptions from the last attempt |
| `test_output` | `str` | Captured output for the last verification attempt |
| `branch` | `str or None` | Model-proposed branch; may be set without creating a Git branch |
| `pr_url` | `str or None` | Created pull request URL, when present |
| `issue_number` | `int or None` | Issue number for issue-based runs |
| `dry_run` | `bool` | Whether the run stopped after planning |

`changed_files` contains values like `created src/example.py`; it is not a plain path list or a cumulative diff across attempts. Use Git to inspect the complete resulting changes.

## Progress events

The current event kinds are `issue`, `context`, `plan`, `implement`, `tests`, and `pr`. The implementation event reports attempts and edit descriptions; the tests event reports pass, failure, or skipped verification. Callbacks run synchronously and callback exceptions can interrupt the run.

## Integration boundaries

Use a separate checkout per concurrent task. Runs write files, execute commands, and may mutate Git state. Explicit API keys change the process environment. This API is not a built-in job queue or a sandboxed multi-tenant service.
