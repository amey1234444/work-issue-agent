# Testing

- Every behavioural change ships with a test.
- Tests live under `tests/` and are runnable with `pytest -q`.
- A bug fix must include a regression test that fails before the fix.
- Do not weaken or delete existing tests to make a change pass.
