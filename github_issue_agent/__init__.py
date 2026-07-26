"""work-issue-agent: a tool-calling AI coding agent for GitHub issues.

The agent investigates a repository through tools (search, read, patch, run),
validates its own change, resolves merge conflicts with the base branch, and
opens a pull request. Commands are defined as markdown workflow files under
``.ai/workflows/`` and the target repository's own instruction files (AGENTS.md,
README.md, CONTRIBUTING.md, ``.ai/rules/*``) are the source of truth for how the
agent behaves.
"""

__version__ = "0.2.0"

from .api import (
    AgentError,
    WorkflowResult,
    fix_pull_request_conflicts,
    resolve_conflicts,
    run_workflow,
    work_issue,
)
from .merge import ResolutionResult, detect_conflicts, sync_with_base
from .patcher import PatchError, apply_patch
from .repo_map import build_repo_map

__all__ = [
    "__version__",
    "AgentError",
    "PatchError",
    "ResolutionResult",
    "WorkflowResult",
    "apply_patch",
    "build_repo_map",
    "detect_conflicts",
    "fix_pull_request_conflicts",
    "resolve_conflicts",
    "run_workflow",
    "sync_with_base",
    "work_issue",
]
