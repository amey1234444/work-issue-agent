# Contributing Guidelines

Thank you for considering contributing to this project! Please follow these short guidelines to keep the repository healthy and consistent.

## Development Environment

1. **Clone the repository** and navigate into it.
2. Create a virtual environment and activate it:
   ```bash
   python -m venv .venv
   source .venv/bin/activate   # on Windows use `.venv\Scripts\activate`
   ```
3. Install the package in editable mode with development dependencies:
   ```bash
   pip install -e "[dev]"
   ```
   This installs the library plus tools needed for linting, type‑checking and testing.

## Linting & Type‑Checking

Run the project’s linting and static analysis tools to ensure code quality:
```bash
ruff check .
# (optional) mypy can be added later if type‑checking is required
```

## Testing

All tests live under the `tests/` directory and can be executed with:
```bash
pytest -q
```
Make sure the test suite passes before opening a pull request.

## Branch & Pull Request Workflow

1. **Create a branch** for your change, using a short kebab‑case name (e.g., `fix-typo` or `add-feature-x`).
2. Commit frequently with clear, conventional‑commit‑style messages.
3. Push the branch to your fork and open a pull request against the default branch.
4. The PR description should:
   - Summarise what was changed and why.
   - Reference the related issue (e.g., `Closes #123`).
   - Mention any relevant documentation updates.

## General Guidelines

- Follow the project's **AGENTS.md** for coding style, testing, and other policies.
- Keep changes minimal and focused; avoid unrelated refactoring.
- **Add or update tests** for any behavioural change (see `tests/` for examples).
- Ensure the code complies with the linting rules (`ruff check .`).

By adhering to these guidelines, you help maintain a clean codebase and a smooth review process. Happy coding!
