---
title: Custom workflows
description: Turn a Markdown file into a repeatable engineering command.
group: Build with the agent
order: 6
source: .ai/workflows/work-issue.md
---

Every `.ai/workflows/<name>.md` in a target repository becomes a command. Workflows describe goals, steps, and constraints in plain Markdown. They are instructions to the model, not executable workflow graphs or hard enforcement rules.

## Included examples

The source repository contains three workflows:

| Workflow | Purpose |
| --- | --- |
| `work-issue` | Read an issue, plan and implement a focused change, verify, and prepare PR metadata |
| `fix-bug` | Reproduce a bug, add a regression test, and implement a minimal fix |
| `add-feature` | Define acceptance criteria, implement a feature and tests, and update documentation |

Copy or adapt the ones you need into your target repo. The package does not install them there automatically.

## Create a workflow

Create `.ai/workflows/improve-docs.md`:

```markdown
# Workflow: Improve Documentation

## Goal
Make the requested behavior easy to understand and verify.

## Steps
1. Read the task and the repository instructions.
2. Inspect the implementation before describing its behavior.
3. Update the smallest relevant set of documentation files.
4. Add runnable examples where they clarify the task.
5. Run the repository's documentation checks.
6. Explain what changed in the pull request.

## Constraints
- Do not invent unsupported flags or capabilities.
- Preserve working links and established terminology.
- Do not change production behavior for a documentation task.
```

Then discover and run it:

```bash
github-issue-agent list --path .
github-issue-agent run improve-docs \
  --prompt "Explain how to configure the test command" \
  --path . --no-pr
```

## Separate instructions from tasks

Use the workflow for repeatable steps. Use `AGENTS.md` and `.ai/rules/*.md` for conventions that apply across workflows. Use `--prompt` or the issue body for the specific acceptance criteria.

## Customize system prompts

The agent checks for `.ai/prompts/planner.md` and `.ai/prompts/coder.md`. When present, each file replaces the corresponding default system prompt.

Preserve the expected response contracts:

```json
{
  "understanding": "Task summary",
  "files_to_read": ["src/example.py"],
  "steps": ["Implement the change", "Run verification"]
}
```

The coder returns `summary`, `branch`, `commit_message`, `pr_title`, `pr_body`, `edits`, and `commands`. Each edit contains `path`, `action` (`create`, `modify`, or `delete`), and complete `content` for create/modify operations. It does not accept patch diffs as file content.

See the exact defaults in [workflow.py](https://github.com/amey1234444/work-issue-agent/blob/main/github_issue_agent/workflow.py) before replacing either prompt.
