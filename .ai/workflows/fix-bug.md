# Workflow: Fix Bug

Goal: reproduce, diagnose and fix a bug, guarding it with a regression test.

## Steps

1. Restate the buggy behaviour and the expected behaviour.
2. Identify the smallest set of files responsible.
3. Add a failing test that reproduces the bug (red).
4. Implement the minimal fix so the test passes (green).
5. Confirm no other behaviour regresses; run the test command.
6. Summarise root cause and fix in the PR body.

## Constraints

- Prefer the smallest change that fixes the root cause, not the symptom.
- The regression test must fail without the fix and pass with it.
