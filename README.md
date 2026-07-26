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

runs a **continuous tool-calling loop** (the default `agent` mode):

```
Issue + repository instructions + repository map
             ↓
     the model chooses a tool
             ↓
 search / read / find symbols / run commands
             ↓
   result returned into the SAME conversation
             ↓
     small apply_patch edits
             ↓
     tests + lint + type-check
             ↓
  failures fixed with the accumulated context
             ↓
   diff review + completion gate
             ↓
  auto-resolve conflicts with base ▸ Commit ▸ Push ▸ PR
```

The whole repository is never dumped into the prompt. The model starts from a
compact repository map (paths, languages, symbols, build and test files) and
pulls in exactly the lines it needs through tools.

The legacy single-shot pipeline (plan → implement whole files → test → retry) is
still available with `--mode workflow`.

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
Success: no issues found in 36 source files

$ pytest -q
........................................................................ [100%]
75 passed in 0.39s
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
| `AGENT_MODE`         | `agent` (tool loop, default) or `workflow` (legacy)          |
| `AGENT_MAX_STEPS`    | max tool calls per agent run (default 60)                    |
| `AGENT_AUTO_RESOLVE_CONFLICTS` | set to `0` to disable automatic conflict resolution |

`.ai/config.yaml` accepts the same knobs plus `validation_commands`,
`allowed_commands` (extra executables the agent may run) and
`conflict_preference` (`ours`/`theirs`).

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

Useful flags:

- `--dry-run` — plan only, make no edits (great for inspecting what the agent intends).
- `--no-pr` — apply edits and run tests locally, but don't commit/push/open a PR.
- `--provider mock|anthropic|openai|openrouter` — override the provider for one run.
- `--base <branch>` — base branch for the PR (defaults to the repo's default branch).
- `--mode agent|workflow` — tool loop (default) or the legacy single-shot pipeline.
- `--max-steps N` — cap the number of tool calls in agent mode (default 60).
- `-v/--verbose` — print every tool call as it happens.

Inspect what the agent sees before it starts:

```bash
github-issue-agent map --path /path/to/repo
```

### Merge conflicts

Conflicts are detected and resolved automatically before a PR is opened, and the
same machinery is available on its own:

```bash
# Resolve a merge/rebase that is already conflicted in your working tree
github-issue-agent resolve-conflicts --path /path/to/repo

# Merge (or rebase onto) a base branch, resolving whatever conflicts appear
github-issue-agent resolve-conflicts --base main --strategy merge
github-issue-agent resolve-conflicts --base main --strategy rebase --prefer theirs

# Take a conflicted pull request, merge its base in, resolve, and push
github-issue-agent fix-pr https://github.com/org/repo/pull/42 --path /path/to/repo
```

How resolution works:

1. **Detect** — unmerged index entries (`git diff --name-only --diff-filter=U`)
   plus a scan for stray conflict markers. `rerere` and `diff3` markers (which
   include the merge base) are enabled so previous resolutions are reused and the
   base version is available.
2. **Deterministic strategies** — identical sides, whitespace-only differences,
   one empty side, one side unchanged from the base, supersets, and additive
   unions (imports, dependency lists, config entries) are resolved without an LLM.
3. **Semantic escalation** — anything genuinely divergent (e.g. both sides changed
   the same function body) is sent to the model with the base, both sides, and
   surrounding context; generated lockfiles are escalated rather than guessed.
4. **Verification** — a resolution containing conflict markers is rejected,
   Python and JSON files must still parse, and the repository's tests/lint run
   afterwards.
5. **Safety** — if anything cannot be resolved or validation fails, the merge or
   rebase is aborted and the branch is left exactly as it was. Nothing is
   force-pushed and the merge is only committed once it is clean.

Use `--no-llm` for deterministic-only resolution, `--prefer ours|theirs` to force
a side, and `--guidance "..."` to give the model project-specific instructions.

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
print(result.tool_calls)     # every tool the agent invoked (agent mode)
```

Conflict resolution is importable too:

```python
from github_issue_agent import resolve_conflicts, fix_pull_request_conflicts

result = resolve_conflicts(repo_path=".", base="main")
print(result.fully_resolved, result.report())

fix_pull_request_conflicts("https://github.com/org/repo/pull/42", repo_path=".")
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

**A run is considered successful when** the code compiles/runs, the test command
exits 0, and (if `open_pr=True`) a PR is opened. `WorkflowResult` reports
`tests_passed`, `pr_url`, `summary`, `changed_files`, `plan`, and `branch`.

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

## How a run works (agent mode)

1. **Stable context** — repository instructions (`AGENTS.md`, `.ai/rules/*`), the
   issue and its acceptance criteria, environment facts, and a repository map
   (`github_issue_agent/repo_map.py`) of paths, languages, symbols and build files.
   No file contents.
2. **Tools** (`github_issue_agent/tools/`) — `list_files`, `read_file`,
   `search_code`, `find_symbol`, `find_references`, `run_command`,
   `read_command_output`, `apply_patch`, `get_git_diff`, `update_plan`. Every
   output is bounded and says how to fetch more; full command logs are kept out
   of the conversation and retrieved on demand.
3. **Edits** (`github_issue_agent/patcher.py`) — the model sends context diffs in
   an `*** Begin Patch` envelope, never whole files. Patches apply atomically:
   if one hunk fails, nothing is written and the error explains why.
4. **Validation** (`github_issue_agent/validation/`) — commands run through an
   allowlist (no shell metacharacters, no `git push/reset/clean`), and failures
   come back as a focused report (failing test IDs, messages, trimmed traceback)
   instead of a wall of log output.
5. **Completion gate** (`github_issue_agent/agent/completion_gate.py`) — the model
   cannot declare victory: the gate checks that files changed, that validation
   actually ran and passed, and scans the diff for skipped tests, deleted
   assertions, blanket `# type: ignore`/`noqa` and `continue-on-error`.
6. **Merge + PR** (`github_issue_agent/merge/`, `git_ops.py`, `github_client.py`) —
   the base branch is merged in with automatic conflict resolution, then the
   branch is pushed (the token is passed per-invocation and never written to
   `.git/config`) and a PR is opened.

Long runs are kept affordable by compacting older tool traffic into a summary
while preserving the original brief and the most recent turns
(`github_issue_agent/agent/state.py`).

## Project layout

```
github_issue_agent/
  api.py            # importable library API: work_issue() / run_workflow() / resolve_conflicts()
  cli.py            # argparse entrypoint; turns .ai/workflows/*.md into commands
  config.py         # .env + env + .ai/config.yaml loading
  context.py        # gather instruction files + file tree + selected files
  repo_map.py       # lightweight map: paths, languages, symbols, build/test files
  patcher.py        # apply_patch envelope parser + atomic applier
  agent/            # the continuous loop
    loop.py         #   tool execution, gating, retries
    prompt.py       #   system instructions + initial brief
    state.py        #   conversation state + compaction
    completion_gate.py  # "done when" contract
    text_protocol.py    # tool calling for complete()-only providers
  tools/            # list_files, read_file, search_code, find_symbol, run_command,
                    # apply_patch, get_git_diff, update_plan ...
  validation/       # command allowlist, failure parser, anti-cheating scanner
  merge/            # conflict parsing, deterministic strategies, resolver
  github_client.py  # fetch issues/PRs, create repos/PRs (GitHub REST)
  llm.py            # provider abstraction: anthropic | openai | openrouter | mock
  workflow.py       # legacy planning/coding loop + robust JSON extraction
  editor.py         # apply file edits safely
  runner.py         # run tests/lint and capture output
  git_ops.py        # branch / commit / push / merge / rebase / conflict helpers
  models.py         # typed dataclasses (Issue, PullRequest, Plan, FileEdit, ...)
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
