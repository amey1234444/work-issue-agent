---
title: Introduction
description: Your repository sets the rules. The agent does the work.
group: Start here
order: 1
---

Work Issue Agent is a workflow-driven AI coding agent for local repositories. Give it a GitHub issue or a task, and it reads your instructions, makes a plan, writes implementation code and tests, runs verification, and can open a pull request.

The repository is the behavior specification. Markdown files in `.ai/workflows/` define commands. `AGENTS.md`, other instruction files, and `.ai/rules/` tell the agent how to work.

## The workflow

1. **Read the task.** Fetch an issue's title, body, and labels, or accept a free-form prompt.
2. **Collect context.** Read repository instructions, rule files, and the file tree.
3. **Plan.** Ask the selected model for the steps and files it needs to read.
4. **Implement.** Apply complete file edits returned by the model.
5. **Verify and iterate.** Run the test commands; feed failures back into the implementation step.
6. **Open a pull request.** Create a branch, commit, push, and open a PR when enabled.

## Three ways to start

| Goal | Starting point |
| --- | --- |
| Try the workflow without model keys | [Quickstart: local mock run](/docs/quickstart/) |
| Resolve a real GitHub issue | [Installation](/docs/installation/) and [CLI reference](/docs/cli/) |
| Integrate it into Python or a notebook | [Python API](/docs/python-api/) |

## Know the package names

| Surface | Name |
| --- | --- |
| GitHub repository | `amey1234444/work-issue-agent` |
| Python distribution | `github-issue-agent` |
| Python import | `github_issue_agent` |
| CLI executable | `github-issue-agent` |
| CLI alias | `ai-agent` |

## What you control

Choose Anthropic, OpenAI, OpenRouter, or the deterministic mock provider. Define your own workflows and prompts, configure the test command, and decide whether to stop after planning, keep edits local, or open a PR.

This is a local CLI and Python library, released under the MIT license. It processes one task at a time and uses the toolchain installed on your machine. The website documents the tool; agent runs happen in your own environment.

## Understand the result

Model quality, repository instructions, and test coverage all affect the outcome. Passing tests are useful evidence, but review the diff and the actual test output. In version 0.1.0, `tests_passed` is also true when verification is skipped, and PR creation is not blocked by exhausted test failures. See [Verification and results](/docs/verification/) before enabling automatic PR creation.

## A real example

The project README records a run that read issue #2, created contribution guidelines, ran `pytest -q`, and opened PR #3. Inspect the original [issue](https://github.com/amey1234444/work-issue-agent/issues/2) and [pull request](https://github.com/amey1234444/work-issue-agent/pull/3) for the result.
