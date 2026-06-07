# work-issue-agent

A small, **workflow-driven AI coding agent**. Instead of hardcoding behaviour into
the agent, the agent is driven by:

1. **Slash-style commands** that map to markdown **workflow files** in `.ai/workflows/`.
2. The target repository's own **instruction files** (`AGENTS.md`, `README.md`,
   `CONTRIBUTING.md`, `.github/copilot-instructions.md`, `.ai/rules/*`) — these are
   the source of truth for *how* the agent should behave.

```
ai-agent work-issue https://github.com/org/repo/issues/123
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

## Install

```bash
git clone <this-repo>
cd work-issue-agent
python -m venv .venv && source .venv/bin/activate
pip install -e ".[all]"     # or .[anthropic] / .[openai]
```

## Configure

Copy `.env.example` to `.env` and fill in:

```bash
cp .env.example .env
```

| Variable             | Purpose                                              |
|----------------------|------------------------------------------------------|
| `LLM_PROVIDER`       | `anthropic` \| `openai` \| `mock`                    |
| `ANTHROPIC_API_KEY`  | required when provider is `anthropic`                |
| `OPENAI_API_KEY`     | required when provider is `openai`                   |
| `GITHUB_TOKEN`       | classic PAT with `repo` scope (read issues, open PR) |
| `AGENT_MAX_ITERATIONS` | self-correction loops on test failure (default 3)  |

`mock` needs no API key and returns a deterministic response — handy for trying
the pipeline end-to-end offline.

## Usage

List the commands available in a repo (discovered from `.ai/workflows/`):

```bash
ai-agent list --path /path/to/target/repo
```

Resolve an issue and open a PR:

```bash
ai-agent work-issue https://github.com/org/repo/issues/123 --path /path/to/repo
```

Run any workflow with a free-form prompt instead of an issue:

```bash
ai-agent run add-feature --prompt "Add a --json flag to the export command" --path .
```

Useful flags:

- `--dry-run` — plan only, make no edits (great for inspecting what the agent intends).
- `--no-pr` — apply edits and run tests locally, but don't commit/push/open a PR.
- `--provider mock|anthropic|openai` — override the provider for one run.
- `--base <branch>` — base branch for the PR (defaults to the repo's default branch).

## How a run works

1. **Context** (`agent/context.py`) — reads instruction files, `.ai/rules/*`, and a
   `git ls-files` file tree of the target repo.
2. **Plan** (`agent/workflow.py::Agent.plan`) — the LLM returns a JSON plan listing the
   files it needs to read and the steps it will take.
3. **Implement** (`Agent.implement`) — the agent loads the requested files and the LLM
   returns JSON file edits + a test command + PR metadata.
4. **Apply & test** (`agent/editor.py`, `agent/runner.py`) — edits are applied (with a
   guard against escaping the repo root) and the test command runs. On failure the
   output is fed back to the LLM, up to `AGENT_MAX_ITERATIONS`.
5. **PR** (`agent/git_ops.py`, `agent/github_client.py`) — branch, commit, push and open
   a pull request via the GitHub REST API.

## Project layout

```
agent/
  cli.py            # argparse entrypoint; turns .ai/workflows/*.md into commands
  config.py         # .env + env + .ai/config.yaml loading
  context.py        # gather instruction files + file tree + selected files
  github_client.py  # fetch issues, create repos/PRs (GitHub REST)
  llm.py            # provider abstraction: anthropic | openai | mock
  workflow.py       # planning/coding loop + robust JSON extraction
  editor.py         # apply file edits safely
  runner.py         # run tests/lint and capture output
  git_ops.py        # branch / commit / push helpers
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
  via `ai-agent run <name>`.
- **Different behaviour per repo**: edit that repo's `AGENTS.md` / `.ai/rules/*`.
- **Custom prompts**: add `.ai/prompts/planner.md` or `.ai/prompts/coder.md`.

This is the Option 1 (local CLI MVP) from the design discussion. The clean module
boundaries make it straightforward to later wrap in a backend service, a queue and
multiple specialised agents (planner/coder/tester/reviewer) once the MVP reliably
solves issues.

## License

MIT
