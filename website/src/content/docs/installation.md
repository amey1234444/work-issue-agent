---
title: Installation
description: Set up the CLI, provider SDKs, and your target repository.
group: Start here
order: 3
source: pyproject.toml
---

## Requirements

- Python **3.10+**.
- Git and a local checkout the agent can modify.
- Your target project's build and test toolchain: for example, pytest, Node.js, or a JDK and Maven.
- A provider API key for real model runs.
- A GitHub token for issue retrieval or PR creation.

## Install from PyPI

```bash
# OpenAI and OpenRouter
python -m pip install "github-issue-agent[openai]"

# Anthropic
python -m pip install "github-issue-agent[anthropic]"

# All real providers
python -m pip install "github-issue-agent[all]"

# Mock provider only
python -m pip install github-issue-agent
```

## Use a virtual environment

On macOS or Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

On Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Run the chosen install command after activation.

## Install from source

```bash
git clone https://github.com/amey1234444/work-issue-agent.git
cd work-issue-agent
python -m pip install -e ".[dev,all]"
```

Or install the latest repository code directly:

```bash
python -m pip install "github-issue-agent[openai] @ git+https://github.com/amey1234444/work-issue-agent.git"
```

## Check the installation

```bash
github-issue-agent --version
github-issue-agent --help
python -c "from github_issue_agent import work_issue; print('Import OK')"
```

The executable is `github-issue-agent`; the import uses underscores: `github_issue_agent`. The CLI also has the alias `ai-agent`.

## Prepare the target repository

The target is the repository being changed, which may be different from the agent's own repository. It needs the relevant `.ai/workflows/<name>.md` file. Add clear instructions and a test command before your first real run.

```yaml
# .ai/config.yaml in your target repository
test_command: pytest -q
rules_glob: .ai/rules/*.md
instruction_files:
  - AGENTS.md
  - README.md
  - CONTRIBUTING.md
```

Replace `pytest -q` with your project's actual verification command. See [Quickstart](/docs/quickstart/) for a complete first run.
