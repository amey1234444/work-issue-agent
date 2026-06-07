# Workflow: Work Issue

Goal: take a GitHub issue and produce a focused, tested pull request that resolves it.

## Steps

1. Read the issue title, body and labels carefully. Restate the problem.
2. Read the repository instruction files (AGENTS.md, README, CONTRIBUTING) and obey them.
3. Locate the modules/files most likely involved. Request only those you must read.
4. Produce a minimal implementation plan.
5. Implement the change. Return COMPLETE file contents for every edited file.
6. Add or update tests that prove the fix/behaviour.
7. Provide a test command (e.g. `pytest -q`) so the change can be verified.
8. Write a clear PR title and body that explains what changed and why, and
   references the issue (e.g. "Closes #123").

## Constraints

- Keep the diff as small as possible; do not refactor unrelated code.
- Never modify generated files by hand.
- Follow the project's existing style and conventions.
