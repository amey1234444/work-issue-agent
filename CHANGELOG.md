# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.2.0] - 2026-09-07

Hardening release: the agent now refuses to report success it cannot prove,
never touches the developer's checkout, and keeps credentials out of every
place they used to leak.

### Added
- `validation.py`: required checks come from the repo (`test_command` + `checks`),
  each run records status (`passed|failed|not_run|skipped|blocked|stale`), exit
  code, argv, duration, output and the tree hash it ran against. Evidence is
  written into the PR body and the JSON result.
- `workspace.py`: every run executes in a disposable `git worktree` under
  `.agent_work/<run_id>/` on its own branch; the developer's branch, index and
  untracked files are never modified. Failed runs keep the worktree for
  inspection.
- `paths.py`: one `PathPolicy` used by context loading, file reads, edits and
  backups. Rejects absolute paths, `..`, symlink escapes, `.git/`, `.env*`, keys
  and credential files, plus repo-configured `protected_paths`.
- `errors.py`: typed `AgentError` with stable `code`, `phase`, `retryable`,
  `recovery` and process exit code; `CancelledError`.
- CLI: `--json` (structured result / structured error on stdout), stable exit
  codes, `init` (scaffold `.ai/`), `doctor` (environment diagnostics), `--model`,
  `--allow-unvalidated`, `--no-isolate`; SIGINT/SIGTERM cancel the run cleanly.
- Config: `checks`, `require_validation`, `draft_pr`, `protected_paths`,
  `protected_branches`, `deadline_seconds`, `command_timeout`; run-scoped
  `api_key`; full type validation of `.ai/config.yaml`.
- Durable per-run checkpoint at `.agent_work/<run_id>.json`.
- GitHub client: retries with backoff for transient failures, request timeouts,
  rate-limit detection, paginated comments, rejects PR URLs passed as issues,
  and idempotent PR creation (reuses an existing open PR, reconciles after 422).
- Issue repository must match the checkout's `origin` (`allow_repo_mismatch`).
- CI workflow on pull requests (Python 3.10–3.12 + macOS) with a wheel install
  smoke test; tag-driven release workflow that verifies tag == version and a
  changelog entry before publishing.

### Changed
- `apply_edits()` is transactional and returns `list[FileChange]` (path, action,
  old/new hash). On any failure every touched file is restored byte-for-byte,
  including mode and directories created by the transaction. `create` on an
  existing file and `modify`/`delete` on a missing file are errors.
- Model output is parsed with a real JSON decoder (braces inside strings are
  safe) and validated against a schema; malformed replies raise
  `ModelOutputError` and are fed back to the model instead of crashing.
- Commands run without a shell (`shlex.split` + `Popen`), with a scrubbed
  environment (no `*TOKEN*`, `*SECRET*`, `*API_KEY*`, ...), bounded output, a
  per-command timeout and a run deadline; the whole process group is killed on
  timeout or cancellation.
- Only the change manifest is staged (`git add -A -- <paths>`), never the whole
  tree. Branch names are validated; protected or existing branches are never
  reused (a unique `agent/...` name is chosen). `git checkout -B` is gone.
- `git push` authenticates through a one-shot credential helper; the token is
  never written to argv, the remote URL or `.git/config`.
- PRs are opened as drafts by default (`draft_pr: false` to change).
- `WorkflowResult` gained `run_id`, `status`, `validation`, `changes`, `commit`,
  `base`, `workspace`; `tests_passed`/`changed_files`/`test_output` remain as
  compatibility properties.
- PyPI publishing now happens only from `vX.Y.Z` tags instead of every push to
  `main`.

### Removed
- `authed_remote()` and the practice of embedding the token in the remote URL.
- Provider API keys are no longer written into `os.environ`.

## [0.1.0]

Initial release: workflow-driven plan → implement → test → PR loop with
Anthropic, OpenAI, OpenRouter and mock providers.
