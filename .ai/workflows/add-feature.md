# Workflow: Add Feature

Goal: implement a new, well-tested feature described by the task/prompt.

## Steps

1. Restate the feature and its acceptance criteria.
2. Survey existing patterns and reuse them (don't invent new conventions).
3. Plan the public interface (functions/CLI flags/endpoints) before coding.
4. Implement the feature with complete file contents.
5. Add tests covering the happy path and at least one edge case.
6. Update README/docs if user-facing behaviour changed.
7. Provide a test command and write a descriptive PR.

## Constraints

- Match the surrounding code style and typing conventions.
- Keep the feature self-contained; avoid sweeping refactors.
