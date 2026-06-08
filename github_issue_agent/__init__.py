"""work-issue-agent: a workflow-driven AI coding agent.

Commands are defined as markdown workflow files under ``.ai/workflows/`` and the
target repository's own instruction files (AGENTS.md, README.md, CONTRIBUTING.md,
``.ai/rules/*``) are treated as the source of truth for how the agent behaves.
"""

__version__ = "0.1.0"

from .api import AgentError, WorkflowResult, run_workflow, work_issue

__all__ = [
    "__version__",
    "AgentError",
    "WorkflowResult",
    "run_workflow",
    "work_issue",
]
