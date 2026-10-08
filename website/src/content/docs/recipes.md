---
title: Task recipes
description: Practical patterns for bugs, features, documentation, notebooks, and controlled runs.
group: Build with the agent
order: 7.5
source: .ai/workflows/fix-bug.md
---

Each recipe assumes a prepared target checkout and the named workflow file under `.ai/workflows/`. The agent's source repository supplies `work-issue`, `fix-bug`, and `add-feature`; other names must be created by you.

## Fix a reproducible bug

```bash
github-issue-agent run fix-bug \
  --prompt "The parser raises on an empty input. Return an empty result. Add a regression test and preserve existing behavior for non-empty inputs." \
  --provider openai --path ./target-repo --no-pr
```

Prepare `.ai/workflows/fix-bug.md` to require a regression test and a minimal fix. Ask for a concrete behavior; avoid “improve the parser” without examples or acceptance criteria.

## Add a small feature

```bash
github-issue-agent run add-feature \
  --prompt "Add an optional --json output flag. Keep the default text output unchanged. Add tests for both formats and update the command help." \
  --provider openai --path ./target-repo --no-pr
```

State compatibility requirements and what should happen when the option is absent. Make sure the target's workflow and verification command match its actual stack.

## Add context to a GitHub issue

```bash
github-issue-agent run work-issue \
  --issue https://github.com/OWNER/REPO/issues/123 \
  --prompt "Preserve the public function signature and cover the empty-input case." \
  --path ./target-repo --no-pr
```

The issue content and prompt are combined. A GitHub token is needed even though this run will not publish.

## Documentation-only work

Create `.ai/workflows/improve-docs.md` using the [custom workflow guide](/docs/workflows/), then:

```bash
github-issue-agent run improve-docs \
  --prompt "Document the existing configuration precedence. Verify each claim against config.py and include a runnable example. Do not change runtime behavior." \
  --path ./target-repo --no-pr
```

If the project has link or documentation checks, use them as the configured fallback. The agent may still return its own commands; inspect the execution output.

## A completely local smoke test

```bash
github-issue-agent run work-issue \
  --prompt "Try the pipeline" --provider mock --no-pr --dry-run
```

This needs no API keys. Remove `--dry-run` in a practice checkout to create the fixed `AGENT_NOTES.md` file and run any configured fallback tests. Mock does not implement arbitrary tasks.

## Drive it from a notebook

Install into the notebook kernel's Python environment:

```python
%pip install "github-issue-agent[openai]"
```

Then use a prepared local checkout and environment-based credentials:

```python
import os
from github_issue_agent import work_issue

result = work_issue(
    "https://github.com/OWNER/REPO/issues/123",
    repo_path="./target-repo",
    provider="openai",
    api_key=os.environ["OPENAI_API_KEY"],
    github_token=os.environ["GITHUB_TOKEN"],
    open_pr=False,
    on_event=lambda kind, message: print(kind, message),
)
print(result.test_output)
```

The notebook environment still needs Git, a real checkout, workflow files, and the project's test toolchain. Avoid embedding credentials in saved notebook cells.

## Use another language or build system

The orchestration is Python, but source edits can target other languages through the selected model. Put the actual requirements in `AGENTS.md`: for example, a JDK version, Maven conventions, a test command, and any files that must not be rewritten wholesale.

```yaml
# Example for a Maven project; adapt to your repository.
test_command: mvn test
instruction_files:
  - AGENTS.md
  - README.md
rules_glob: .ai/rules/*.md
```

The agent does not provision these runtimes or containers for you. Verify the baseline command locally first.

## Reduce the iteration budget

```python
from github_issue_agent import run_workflow

result = run_workflow(
    "fix-bug",
    prompt="Handle empty input",
    repo_path="./target-repo",
    max_iterations=1,
    open_pr=False,
)
```

This allows one implementation attempt with no test-driven correction after it. It does not cap token usage or guarantee provider cost. There is no CLI `--max-iterations`; use `AGENT_MAX_ITERATIONS` for the CLI.
