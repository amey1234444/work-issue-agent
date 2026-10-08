---
title: User manual
description: The complete operating guide, from a clean checkout to a reviewed pull request.
group: Start here
order: 2.5
source: github_issue_agent/api.py
---

This manual walks through using Work Issue Agent as a local CLI and a Python library. Start with the mock walkthrough, prepare your own repository, inspect a real model's plan, then apply and review changes before enabling publication.

[Download this manual as Markdown](/manual.md) · [Explore the animated architecture](/architecture/)

## 1. Choose your first task

Choose a small, testable issue with explicit acceptance criteria. Good first tasks include handling an empty input, adding an optional CLI flag, or updating a clearly scoped documentation page.

A useful issue explains:

1. The current behavior, with a reproducible example.
2. The expected behavior and relevant edge cases.
3. Constraints: compatibility, style, files that must not change.
4. A command or test that proves the change works.

For example: “The CSV exporter raises an exception for an empty record list. Return a header-only CSV instead. Preserve the existing column order. Add an empty-input regression test and run the exporter test suite.”

Avoid combining unrelated features into one run. The agent handles one workflow task at a time; it does not automatically triage an entire issue backlog.

## 2. Understand the three run modes

| Mode | CLI | Reads context and plans | Edits and verifies | Commits, pushes, opens PR |
| --- | --- | --- | --- | --- |
| Preview | `--dry-run` | Yes | No | No |
| Local | `--no-pr` | Yes | Yes | No |
| Full workflow | Neither flag | Yes | Yes | Yes, if changes exist and GitHub operations succeed |

Use preview first and local mode second. An issue URL always requires a GitHub token. For a prompt-only plan without GitHub authentication, combine `--dry-run --no-pr`.

`--no-pr` still edits files and executes shell commands. It only disables publication.

## 3. Install in a Python environment

You need Python 3.10+, Git, and the real test/build tools for the target project.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install "github-issue-agent[openai]"
github-issue-agent --version
```

For Windows PowerShell, use `py -m venv .venv`, then `.\.venv\Scripts\Activate.ps1`. The `[openai]` extra supports OpenAI and OpenRouter. Use `[anthropic]` for Anthropic, `[all]` for both SDKs, or no extra for mock-only use.

The names have different separators: install `github-issue-agent`, import `github_issue_agent`, and run `github-issue-agent` or its alias `ai-agent`.

## 4. Prepare a clean target checkout

The target repository is the project the agent will modify. Clone it separately from unrelated work:

```bash
git clone https://github.com/OWNER/REPO.git target-repo
cd target-repo
git status --short
```

Replace `OWNER/REPO` with your project. Start from the intended base revision with no personal changes. The agent does not check out the `--base` revision for you, and publication stages all changes using `git add -A`.

Install this project's dependencies and run its normal verification command once yourself. If its baseline is already broken, repair or document that before asking the agent to diagnose a new task.

## 5. Add the repository contract

Create these files in the target repository:

| File | What it controls | Starter |
| --- | --- | --- |
| `.ai/workflows/work-issue.md` | Repeatable task steps | [Download workflow](/examples/work-issue.md) |
| `AGENTS.md` | Coding and review conventions | [Download instructions](/examples/AGENTS.md) |
| `.ai/config.yaml` | Instruction paths and fallback verification | [Download configuration](/examples/config.yaml) |

The downloaded instruction and config examples target a Python/pytest repository. Adapt language, test command, and conventions before using them in another stack.

### Workflow file

```markdown
# Workflow: Work Issue

1. Read the task and repository instructions.
2. Inspect the relevant implementation and existing tests.
3. Make a focused plan and list the files to read.
4. Implement the requested behavior and appropriate tests.
5. Run the repository's verification command.
6. Summarize the changes, test output, and remaining limitations.
```

### Repository configuration

```yaml
# .ai/config.yaml
instruction_files:
  - AGENTS.md
  - README.md
  - CONTRIBUTING.md
rules_glob: .ai/rules/*.md
test_command: pytest -q
```

Use your project's real command. The configured `test_command` is a fallback; model-provided commands take priority. A workflow file is a model instruction, not an independently enforced approval gate.

Commit these reviewed setup files to the target repository before a real task run, so the starting checkout is clean. Installing the package alone does not create a target's `.ai/` files.

## 6. Try a mock run first

Use a practice checkout so its fixed demonstration file cannot overwrite important work.

```bash
github-issue-agent list --path .

github-issue-agent run work-issue \
  --prompt "Try the workflow pipeline" \
  --provider mock --dry-run --no-pr --path .

github-issue-agent run work-issue \
  --prompt "Try the workflow pipeline" \
  --provider mock --no-pr --path .
```

The first run returns a plan. The second creates `AGENT_NOTES.md`. Mock returns a fixed implementation; it does not reason about or solve your requested task. If you configured a fallback test command, it still runs that real command. Without one, the mock verification step is skipped.

This prompt-only, no-PR combination requires no model key and no GitHub token.

## 7. Configure a real provider

Create a local `.env` file and add it to `.gitignore` before entering credentials:

```dotenv
LLM_PROVIDER=openai
OPENAI_API_KEY=replace-with-your-provider-key
OPENAI_MODEL=replace-with-a-compatible-model-id
GITHUB_TOKEN=replace-with-your-github-token
AGENT_MAX_ITERATIONS=3
```

The placeholders above are not usable credentials. Select a model available to your provider account and compatible with the adapter. For the complete provider matrix, see [Model providers](/docs/providers/).

The loader preserves existing environment variables, fills missing values from the current directory's `.env`, then from the target repository's `.env`. Explicit Python API overrides take precedence for supported fields.

The current GitHub client documents a classic personal access token with `repo` scope and access to the target repository. It is needed for issue retrieval as well as publication. Do not put credentials in source files, screenshots, issues, or PR bodies.

## 8. Inspect a real plan

```bash
github-issue-agent work-issue \
  https://github.com/OWNER/REPO/issues/123 \
  --path ./target-repo --dry-run
```

Run this from the directory that contains `target-repo`, or use `--path .` from inside it. Substitute the real issue URL.

Check the understanding, file list, and proposed steps. They should match the requested behavior and your repository conventions. If the plan is vague or chooses irrelevant files, improve the issue or instructions before applying edits.

The agent supplies instructions and the tree to the planner first, then reads the files selected by that plan during implementation. Keep instructions concise: each file is truncated at 20,000 characters and the tree is limited to 400 entries.

## 9. Apply and verify locally

```bash
github-issue-agent work-issue \
  https://github.com/OWNER/REPO/issues/123 \
  --path ./target-repo --no-pr
```

Watch the progress output: task retrieval, context, plan, implementation attempt, edited files, and verification result.

If a command fails, the last 6,000 characters of output become feedback for the next implementation. The default is three total implementation attempts. The plan is reused and previous edits stay in the working tree.

The retry loop handles failed verification. It is not a general automatic recovery mechanism for every network, JSON, provider, or Git error.

## 10. Inspect the full result

```bash
git -C ./target-repo status --short
git -C ./target-repo diff --stat
git -C ./target-repo diff
```

Also open newly created untracked files: a normal `git diff` does not show their content until staged. Check the implementation, tests, generated commands, and any deleted files. Run the actual project checks when needed.

| Observation | Interpretation |
| --- | --- |
| Tests ran and exit code is zero | The executed checks passed; review what they covered |
| “No test command specified” | Verification was skipped, even though `tests_passed=True` |
| Final attempt failed | Local changes remain; inspect the last output and full diff |
| Dry run reports success | The plan completed; no code was verified |

The result's file descriptions and test output cover the last attempt, not a cumulative audit log of every attempt.

## 11. Publish deliberately

There are two practical paths after review.

**Publish your reviewed local changes yourself.** Stage only the files you intend, commit them on your chosen branch, push, and open a PR using your usual GitHub workflow. The agent has no dedicated “publish the last no-PR run” command.

**Start a fresh full agent run.** From a clean checkout of the intended base, run the same issue without `--dry-run` or `--no-pr`:

```bash
github-issue-agent work-issue \
  https://github.com/OWNER/REPO/issues/123 \
  --path ./fresh-target-repo --base main
```

This replans and reimplements the task. It does not resume the prior local result. `--base main` chooses the PR target only.

The publication sequence creates the model-proposed branch, stages all changes, commits, pushes, and opens a PR. In version 0.1.0, that sequence can still run after failed tests. Use CI and branch protection to enforce merge requirements.

The current HTTPS helper can leave a credential in the remote URL. Restore a clean origin after the run if needed:

```bash
git -C ./fresh-target-repo remote set-url origin \
  https://github.com/OWNER/REPO.git
```

## 12. Integrate from Python

```python
from github_issue_agent import run_workflow

def progress(kind: str, message: str) -> None:
    print(f"[{kind}] {message}")

result = run_workflow(
    "work-issue",
    prompt="Handle empty records in the CSV exporter",
    repo_path="./target-repo",
    provider="openai",
    open_pr=False,
    max_iterations=3,
    on_event=progress,
)

print(result.plan)
print(result.summary)
print(result.test_output)
print(result.changed_files)
```

Calls are synchronous. Use separate checkouts per concurrent task. Credentials passed through `api_key` are placed in the process environment; this is relevant for shared-service designs. See [Python API](/docs/python-api/) for every argument, field, event, and exception boundary.

## 13. Recover from an interrupted run

Before retrying, inspect the checkout and remote. The run may already have applied files, created a branch, pushed, or opened a PR before a later operation failed. Re-running without inspection can mix edits or reuse a branch name.

- **Provider failure:** check model access, quota, credentials, and the exact error.
- **Invalid JSON:** narrow the task or select a model that reliably follows the response contract.
- **Test failure:** verify the baseline toolchain and read the full command output.
- **GitHub failure:** check repository access and branch restrictions; a successful push may precede a failed PR request.
- **Unexpected edits:** review or restore them using your normal Git workflow before another attempt.

See [Troubleshooting](/docs/troubleshooting/) for symptom-by-symptom guidance.

## 14. A repeatable operating checklist

Before a real task: clean checkout, working baseline checks, workflow present, clear acceptance criteria, correct provider, and sufficient repository access.

Before publication: reviewed diff, inspected new files, known verification commands, understood test output, intended base and branch, and no unrelated files or credentials in the commit.

After publication: inspect the PR and CI, confirm scope, restore a clean remote URL if needed, and let the normal review process decide whether to merge.

Continue with [Task recipes](/docs/recipes/) or the [interactive architecture](/architecture/).
