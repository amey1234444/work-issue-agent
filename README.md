# github-issue-agent

A small, **workflow-driven AI coding agent** that reads a GitHub issue, writes the
code to resolve it (plus tests), verifies the tests pass, and opens a pull
request — autonomously. Instead of hardcoding behaviour into the agent, it is
driven by:

1. **Slash-style commands** that map to markdown **workflow files** in `.ai/workflows/`.
2. The target repository's own **instruction files** (`AGENTS.md`, `README.md`,
   `CONTRIBUTING.md`, `.github/copilot-instructions.md`, `.ai/rules/*`) — these are
   the source of truth for *how* the agent should behave.

- **Python import name:** `github_issue_agent`
- **Pip / distribution name:** `github-issue-agent`
- **CLI command:** `github-issue-agent` (the shorter `ai-agent` is kept as an alias)

```
github-issue-agent work-issue https://github.com/org/repo/issues/123
```

does exactly what you sketched out:

```
Read issue
   ↓
Read repo instructions (AGENTS.md, README, CONTRIBUTING, .ai/rules/*)
   ↓
Build a code map (file tree + selected files)
   ↓
Plan (LLM)
   ↓
Implement file edits (LLM)
   ↓
Run tests  ──fail──▶ feed failure back to LLM (up to N times)
   ↓ pass
Commit ▸ Push ▸ Open PR
```

## Why this design

Commands are **data, not code**. Every `.ai/workflows/<name>.md` automatically
becomes a runnable command, so adding `/fix-bug`, `/add-feature`, `/review-pr`,
etc. is just adding a markdown file — no code changes. The repo itself becomes the
behaviour spec, which scales far better than stuffing everything into one prompt.

## Demo (live run)

A real run against this repository, using the OpenRouter provider with the free
`openai/gpt-oss-120b:free` model:

```bash
LLM_PROVIDER=openrouter OPENROUTER_MODEL=openai/gpt-oss-120b:free \
ai-agent work-issue https://github.com/amey1234444/work-issue-agent/issues/2 --path .
```

Output:

```text
Fetched issue #2: Add a CONTRIBUTING.md with contribution guidelines
Loaded 2 instruction file(s), 2 rule(s).

== Planning (openrouter) ==
Understanding:
  The issue requests adding a new CONTRIBUTING.md file at the repository root ...

Plan:
  1. Create a new file CONTRIBUTING.md at the repository root ...
  2. Ensure the markdown follows the style of existing docs and is concise.
  3. Run the test suite (pytest -q) and lint (ruff check .) ...
  4. Provide the test command (pytest -q) for the PR metadata.

== Implementing (attempt 1/3) ==
Changes:
  created CONTRIBUTING.md
Running: ['pytest -q']
Tests passed.

Summary: Added CONTRIBUTING.md with concise contribution guidelines

Opened PR: https://github.com/amey1234444/work-issue-agent/pull/3
```

The agent read [issue #2](https://github.com/amey1234444/work-issue-agent/issues/2),
planned, wrote `CONTRIBUTING.md`, ran the test suite, and opened
[PR #3](https://github.com/amey1234444/work-issue-agent/pull/3) — fully autonomously:

![Demo: PR opened by the agent](docs/demo-pr3.png)

## Verification

Lint, type-check and the test suite all pass:

```text
$ ruff check .
All checks passed!

$ mypy github_issue_agent
Success: no issues found in 12 source files

$ pytest -q
.......................                                                  [100%]
23 passed in 0.16s
```

(The screenshot below is from an earlier run; the suite has since grown as
features/tests were added.)

![Verification: ruff, mypy and pytest all passing](docs/verification-proof.png)

## Install

From [PyPI](https://pypi.org/project/github-issue-agent/) (recommended — works in
**Google Colab** or any fresh environment):

```bash
pip install "github-issue-agent[openai]"      # or [anthropic] / [all]
```

Then `from github_issue_agent import work_issue` works immediately. The `[openai]`
extra pulls the SDK used for the OpenAI **and** OpenRouter providers; the `mock`
provider needs no extra and no key.

From a local clone (for development):

```bash
git clone https://github.com/amey1234444/work-issue-agent.git
cd work-issue-agent
python -m venv .venv && source .venv/bin/activate
pip install -e ".[all]"     # or .[anthropic] / .[openai]
```

You can also install the latest unreleased code straight from GitHub:

```bash
pip install "github-issue-agent[openai] @ git+https://github.com/amey1234444/work-issue-agent.git"
```

## Configure

Copy `.env.example` to `.env` and fill in:

```bash
cp .env.example .env
```

| Variable             | Purpose                                                      |
|----------------------|--------------------------------------------------------------|
| `LLM_PROVIDER`       | `anthropic` \| `openai` \| `openrouter` \| `mock`            |
| `ANTHROPIC_API_KEY`  | required when provider is `anthropic`                        |
| `OPENAI_API_KEY`     | required when provider is `openai`                           |
| `OPENROUTER_API_KEY` | required when provider is `openrouter`                       |
| `OPENROUTER_MODEL`   | OpenRouter model slug (default `openai/gpt-oss-120b:free`)   |
| `GITHUB_TOKEN`       | classic PAT with `repo` scope (read issues, open PR)         |
| `AGENT_MAX_ITERATIONS` | self-correction loops on test failure (default 3)          |
| `AGENT_DEADLINE_SECONDS` | wall-clock budget for a whole run (default 3600)         |
| `AGENT_COMMAND_TIMEOUT` | per-command timeout for checks (default 1800)             |

Provider and GitHub credentials are **run-scoped**: they are read into the run's
configuration and never written back into the process environment, never placed
in command lines or `.git/config`, and are stripped from the environment of every
command the agent executes (anything that looks like `*TOKEN*`, `*SECRET*`,
`*API_KEY*`, `*PASSWORD*`, ... is removed).

Repo-level settings live in `.ai/config.yaml` (scaffold it with `ai-agent init`):

```yaml
provider: openrouter
test_command: pytest -q          # required check
checks:                          # more required checks; all must pass on the final tree
  - ruff check .
  - mypy src
require_validation: true         # refuse to open a PR unless every required check passed
draft_pr: true                   # open PRs as drafts
protected_paths: ["deploy/**"]   # in addition to .git, .env*, keys, credentials, ...
protected_branches: [main, master, develop, release]
deadline_seconds: 3600
command_timeout: 1800
```

Required checks come from the repository, never from the model: commands the model
suggests are run in addition to them and can never replace them.

`mock` needs no API key and returns a deterministic response — handy for trying
the pipeline end-to-end offline.

**OpenRouter** is an OpenAI-compatible gateway to hundreds of models; a free-tier
key can run `:free` model slugs (e.g. `openai/gpt-oss-120b:free`). Set
`LLM_PROVIDER=openrouter` and `OPENROUTER_API_KEY=...`.

## Usage

List the commands available in a repo (discovered from `.ai/workflows/`):

```bash
github-issue-agent list --path /path/to/target/repo
```

Resolve an issue and open a PR:

```bash
github-issue-agent work-issue https://github.com/org/repo/issues/123 --path /path/to/repo
```

Run any workflow with a free-form prompt instead of an issue:

```bash
github-issue-agent run add-feature --prompt "Add a --json flag to the export command" --path .
```

Scaffold `.ai/` in a new repo and check the environment:

```bash
ai-agent init --path /path/to/repo
ai-agent doctor --path /path/to/repo      # python, git, origin, workflows, config, tools, keys
```

Useful flags:

- `--dry-run` — plan only, make no edits (great for inspecting what the agent intends).
- `--no-pr` — apply edits and run checks in an isolated worktree, but don't commit/push/open a PR.
- `--json` — print a machine-readable result (or a structured error) on stdout; progress goes to stderr.
- `--provider mock|anthropic|openai|openrouter`, `--model <name>` — override for one run.
- `--base <branch>` — base branch for the PR (defaults to the repo's default branch).
- `--allow-unvalidated` — open a PR even if validation did not pass (not recommended; the PR body still shows the real status).
- `--no-isolate` — edit the checkout in place instead of a disposable worktree (not recommended).

### Exit codes

| Code | Meaning                                   |
|------|-------------------------------------------|
| 0    | success                                   |
| 1    | validation failed / not authoritative      |
| 2    | configuration error                       |
| 3    | authentication error                      |
| 4    | LLM provider error                        |
| 5    | workspace / git conflict                  |
| 6    | publication (push / PR) error             |
| 7    | cancelled (SIGINT/SIGTERM)                |
| 8    | budget exhausted (deadline / iterations)  |
| 9    | internal error                            |

With `--json`, errors are printed as `{"error", "code", "phase", "retryable", "recovery"}`
so callers can act on them. Every run also writes a checkpoint to
`.agent_work/<run_id>.json` in the target repo (add `.agent_work/` to `.gitignore`;
`ai-agent init` does this for you).

## Use as a library

The agent is also importable, so you can drive a run from your own Python code,
a backend service or a notebook — pass the API key and issue URL as arguments
and it does the rest:

```python
from github_issue_agent import work_issue

result = work_issue(
    "https://github.com/org/repo/issues/123",
    provider="openrouter",            # "anthropic" | "openai" | "openrouter" | "mock"
    api_key="sk-or-...",              # optional; falls back to the provider's env var
    model="z-ai/glm-4.5-air:free",    # optional; overrides the default for the provider
    repo_path="/path/to/local/checkout",
    github_token="ghp_...",           # optional; falls back to GITHUB_TOKEN / GITHUB_PAT
    open_pr=True,                     # False = apply + test only, no commit/push/PR
)

print(result.tests_passed)   # bool
print(result.pr_url)         # str | None
print(result.summary)        # the model's summary of what changed
print(result.changed_files)  # list[str]
```

`work_issue(...)` is sugar for `run_workflow("work-issue", issue_url=...)`. Use
`run_workflow(<name>, prompt=...)` to drive any other workflow (e.g. `fix-bug`,
`add-feature`) with a free-form prompt instead of an issue. Pass an `on_event`
callback `(kind, message)` to stream progress, or set `dry_run=True` to get just
the plan. Unrecoverable problems raise `github_issue_agent.AgentError`; everything
else comes back on the `WorkflowResult`.

## How to use — step by step

The most common goal is "resolve issue X and open a PR". Here is the full recipe.

**1. Have a local checkout of the *target* repo** (the repo the issue lives in).
The agent edits and runs tests on a real working copy:

```bash
git clone https://github.com/org/target-repo.git
```

**2. Make sure the target repo has a workflow file.** The agent only runs commands
that exist as `.ai/workflows/<name>.md` in the target repo. At minimum it needs
`.ai/workflows/work-issue.md`. It also reads `AGENTS.md` and `.ai/rules/*` as the
"rules of the house" (e.g. "use Java 21", "only additive `pom.xml` changes"). The
better these instructions, the better the result — see *What to expect* below.

**3. Provide credentials:**
- An **LLM key** for your chosen provider (`OPENROUTER_API_KEY`, `OPENAI_API_KEY`,
  or `ANTHROPIC_API_KEY`). `mock` needs none.
- A **GitHub token** (`GITHUB_TOKEN`, classic PAT with `repo` scope) — only needed
  when you actually want it to open a PR.

**4a. Run it from the CLI:**

```bash
LLM_PROVIDER=openrouter OPENROUTER_MODEL=z-ai/glm-4.5-air:free \
GITHUB_TOKEN=ghp_... OPENROUTER_API_KEY=sk-or-... \
github-issue-agent work-issue https://github.com/org/target-repo/issues/2 \
  --path ./target-repo
```

**4b. …or from Python (e.g. a Colab notebook):**

```python
from github_issue_agent import work_issue

result = work_issue(
    "https://github.com/org/target-repo/issues/2",
    provider="openrouter",
    api_key="sk-or-...",
    model="z-ai/glm-4.5-air:free",
    repo_path="./target-repo",
    github_token="ghp_...",
    open_pr=True,
)
print(result.pr_url, result.tests_passed, result.summary)
```

**5. Inspect the result.** On success you get a PR URL and `tests_passed=True`. Tips:
- Start with `dry_run=True` (library) or `--dry-run` (CLI) to see only the plan.
- Use `open_pr=False` / `--no-pr` to apply edits and run tests **without** pushing —
  good for reviewing the diff locally first.
- Begin with `provider="mock"` to smoke-test the wiring with no key and no network.

## What to expect

**What it actually does.** For each run the agent:

1. **Reads** the issue and the target repo's instruction files + a file tree.
2. **Plans** (LLM) — which files to read and the steps to take.
3. **Implements** (LLM) — writes the **real production code that resolves the issue**
   *and* adds/updates tests. It is not a test-only generator: in the live
   [NEWS-PLATFORM #2](https://github.com/amey1234444/NEWS-PLATFORM/pull/9) run it
   created `RefinerService.java` (the actual feature), wired it into the consumer
   and controller, **and** added 10 JUnit tests.
4. **Verifies** — runs the repo's test command. If it fails, the test output is fed
   back to the model to fix, repeating up to `AGENT_MAX_ITERATIONS` times.
5. **Opens a PR** — branch, commit, push, and open a PR that references the issue.

So the loop is **Plan → Implement (code + tests) → Test → self-correct → PR**. The
tests are how the agent checks its *own* implementation; they are not the deliverable
by themselves.

**A run is considered successful when** every *required* check configured by the
repository (`test_command` + `checks`) ran on the exact final tree and exited 0, and
(if `open_pr=True`) a PR was opened. `WorkflowResult` reports `status`, `run_id`,
`validation` (per-check status, exit code, argv, duration, output and the tree hash
it ran against), `changes` (created/modified/deleted files with hashes), `branch`,
`commit`, `pr_url`, `workspace`, plus the legacy `tests_passed`/`changed_files`.

Validation is **fail-closed**: a PR is only opened when validation status is
`passed`. `failed`, `not_run` (no checks configured), `blocked` (tool missing),
`skipped` or `stale` (the tree changed after the checks ran) all refuse to publish
and explain how to recover. The evidence table is included in the PR body.

**Safety guarantees.**
- The agent never edits your checkout: each run works in a disposable `git worktree`
  under `.agent_work/<run_id>/` on its own branch. Your current branch, staged and
  unstaged changes and untracked files are untouched. Successful runs clean the
  worktree up; failed runs leave it for inspection.
- File edits are transactional: if any edit fails, all files are restored byte-for-byte
  (including modes and directories the edit created). Absolute paths, `..`, symlink
  escapes, `.git/`, `.env*`, keys and credential files are refused.
- Only the files the agent changed are staged and committed — never `git add -A`.
- Model-chosen branch names are validated; protected branches (`main`, `master`, ...)
  and existing branches are never reused, a unique `agent/...` name is picked instead.
- Commands run without a shell, with a scrubbed environment (no tokens), bounded
  output, a per-command timeout and a run deadline; the whole process group is
  killed on timeout or Ctrl-C.
- Pushes use a one-shot credential helper; the token is never written to argv,
  the remote URL or `.git/config`. PR creation is idempotent (an existing open PR for
  the same branch is reused).
- The issue's repository must match the checkout's `origin` (override with
  `allow_repo_mismatch=True`).

**What it is *not*.** It is not magic and not deterministic — output quality depends
on (a) the **model** you pick and (b) the **quality of the repo's `.ai/` rules**.
Honest limitations observed in practice:
- Weak/free models can produce *compiling-but-wrong* code on early attempts (e.g. a
  corrupted `pom.xml`, or a Java regex escaping typo) and only converge after the
  repo's `.ai/rules` are tightened. Stronger models need fewer guardrails.
- It needs the **real toolchain** present to verify (e.g. JDK + Maven for a Java repo,
  or `pytest` for Python). With `open_pr=False` it still plans/edits/tests locally.
- Free-tier API keys have low rate limits; a full run makes several model calls and
  can hit `429`s. Reasoning models are handled automatically (reasoning disabled so
  they return an answer instead of burning the token budget "thinking").
- It works on **one issue at a time** and expects a local checkout it can modify.

**Rule of thumb:** treat it like a junior engineer who follows instructions literally.
Clear `AGENTS.md` + `.ai/rules/*` + a capable model → clean, passing PRs. Vague
instructions + a weak model → it may need a few iterations or a human nudge.

## How a run works

1. **Context** (`github_issue_agent/context.py`) — reads instruction files, `.ai/rules/*`,
   and a `git ls-files` file tree of the target repo.
2. **Plan** (`github_issue_agent/workflow.py::Agent.plan`) — the LLM returns a JSON plan
   listing the files it needs to read and the steps it will take.
3. **Implement** (`Agent.implement`) — the agent loads the requested files and the LLM
   returns JSON file edits + a test command + PR metadata.
4. **Apply & validate** (`editor.py`, `validation.py`, `runner.py`) — edits are applied
   transactionally inside a disposable worktree (`workspace.py`) under a path policy
   (`paths.py`); every required check runs on the final tree and its evidence (argv,
   exit code, output, tree hash) is recorded. On failure the output is fed back to the
   LLM, up to `AGENT_MAX_ITERATIONS`, and the change manifest is carried across retries.
5. **PR** (`git_ops.py`, `github_client.py`) — only if validation passed: stage exactly the
   manifest, commit, push with a one-shot credential helper and open (or reuse) a PR that
   includes the validation evidence.

## Project layout

```
github_issue_agent/
  api.py            # importable library API: work_issue() / run_workflow()
  cli.py            # argparse entrypoint; turns .ai/workflows/*.md into commands
  config.py         # .env + env + .ai/config.yaml loading
  context.py        # gather instruction files + file tree + selected files
  github_client.py  # fetch issues, create repos/PRs (GitHub REST)
  llm.py            # provider abstraction: anthropic | openai | openrouter | mock
  workflow.py       # planning/coding loop + robust JSON extraction
  editor.py         # transactional file edits with rollback + change manifest
  paths.py          # shared path policy (root escape, symlinks, protected files)
  validation.py     # required checks, statuses, evidence, tree hashes
  runner.py         # shell-free command execution: scrubbed env, timeouts, cancel
  workspace.py      # disposable git worktrees so the developer checkout is untouched
  git_ops.py        # branch validation, scoped staging, credential-safe push
  errors.py         # typed errors, stable codes and exit codes
  models.py         # typed dataclasses (Issue, Plan, FileEdit, Implementation)
.ai/
  config.yaml       # which instruction files/rules/test command to use
  workflows/*.md    # the commands (work-issue, fix-bug, add-feature, ...)
  prompts/*.md      # optional overrides for planner/coder system prompts
  rules/*.md        # extra rules injected into context
tests/              # pytest suite
```

## Extending

- **New command**: drop a markdown file in `.ai/workflows/`. It is instantly available
  via `github-issue-agent run <name>`.
- **Different behaviour per repo**: edit that repo's `AGENTS.md` / `.ai/rules/*`.
- **Custom prompts**: add `.ai/prompts/planner.md` or `.ai/prompts/coder.md`.

This is the Option 1 (local CLI MVP) from the design discussion. The clean module
boundaries make it straightforward to later wrap in a backend service, a queue and
multiple specialised agents (planner/coder/tester/reviewer) once the MVP reliably
solves issues.

## License

MIT
