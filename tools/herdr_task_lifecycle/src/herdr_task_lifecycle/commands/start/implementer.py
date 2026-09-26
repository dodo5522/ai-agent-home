"""Start and recover the implementer Agent for one Issue task."""

import hashlib
from pathlib import Path
from typing import Protocol

from herdr_agents import AgentTarget, EnsuredAgent
from herdr_task_state.model import AgentReference, Task, TaskKey

from ...errors import LifecycleError


class TaskAgentManager(Protocol):
    """Generic Agent management consumed by Issue policy."""

    def ensure(self, target: AgentTarget) -> EnsuredAgent:
        """Start or reuse one exact Agent target."""

    def prompt(self, name: str, text: str) -> None:
        """Send a prompt to one named Agent."""


def task_agent_name(task_key: TaskKey) -> str:
    """Return a stable, repository-scoped implementer Agent name."""
    repository_hash = hashlib.sha256(task_key.repository.encode("utf-8")).hexdigest()[:8]
    return f"codex-issue-{task_key.issue_number}-{repository_hash}"


class TaskAgentStarter:
    """Ensure one task's implementer Agent owns the requested Pane."""

    def __init__(self, manager: TaskAgentManager) -> None:
        self._manager = manager

    def ensure_implementer(
        self,
        task_key: TaskKey,
        task: Task,
        pane_id: str,
    ) -> AgentReference:
        """Start the implementer if absent and prompt it exactly once."""
        main = task.workstreams["main"]
        stored = (main.agents or {}).get("implementer")
        name = stored.name if stored is not None else task_agent_name(task_key)
        if task.herdr is None:
            raise LifecycleError("task has no Herdr workspace")
        if main.worktree is None or main.branch is None:
            raise LifecycleError("main workstream has incomplete Git identity")
        result = self._manager.ensure(
            AgentTarget(
                name,
                pane_id,
                task.herdr.workspace_id,
                Path(main.worktree),
                task.herdr.workspace_label,
                task.repository,
                main.branch,
            )
        )
        if result.agent.codex_session_id is None:
            raise LifecycleError("implementer Agent has no Codex session identity")
        if result.disposition == "fresh":
            self._manager.prompt(result.agent.name, self._initial_prompt(task_key, task))
        return AgentReference(
            name=result.agent.name,
            codex_session_id=result.agent.codex_session_id,
        )

    @staticmethod
    def _initial_prompt(task_key: TaskKey, task: Task) -> str:
        main = task.workstreams["main"]
        worktree = main.worktree or "not recorded"
        branch = main.branch or "not recorded"
        return (
            f"Begin implementation for Issue #{task_key.issue_number}: {task.title or 'untitled'}\n"
            f"Repository: {task_key.repository}\n"
            f"Worktree: {worktree}\n"
            f"Branch: {branch}\n"
            "Use the task state and repository instructions as the source of truth."
        )
