"""Start and recover the implementer Agent for one Issue task."""

import hashlib
from pathlib import Path
from typing import Protocol

from herdr_task_state.model import AgentReference, Task, TaskKey

from ...errors import LifecycleError
from ...herdr import AgentInfo


class TaskAgentOperations(Protocol):
    """Herdr operations required by task-scoped Agent startup."""

    def agents(self) -> list[AgentInfo]:
        """Return live Agents."""

    def agent_start(self, name: str, pane_id: str, kind: str = "codex") -> AgentInfo:
        """Start one named Agent on one Pane."""

    def agent_prompt(self, name: str, text: str) -> None:
        """Send a prompt to one named Agent."""


def task_agent_name(task_key: TaskKey) -> str:
    """Return a stable, repository-scoped implementer Agent name."""
    repository_hash = hashlib.sha256(task_key.repository.encode("utf-8")).hexdigest()[:8]
    return f"codex-issue-{task_key.issue_number}-{repository_hash}"


class TaskAgentStarter:
    """Ensure one task's implementer Agent owns the requested Pane."""

    def __init__(self, herdr: TaskAgentOperations) -> None:
        self._herdr = herdr

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
        live = {agent.name: agent for agent in self._herdr.agents()}
        existing = live.get(name)
        if existing is not None:
            if existing.pane_id != pane_id:
                raise LifecycleError(f"Agent {name} is on a different pane")
            if task.herdr is not None and existing.workspace_id != task.herdr.workspace_id:
                raise LifecycleError(f"Agent {name} is in a different workspace")
            if main.worktree is not None and existing.cwd != Path(main.worktree):
                raise LifecycleError(f"Agent {name} has a different cwd")
            return AgentReference(name=name)

        started = self._herdr.agent_start(name, pane_id)
        if started.name != name or started.pane_id != pane_id:
            raise LifecycleError("started implementer Agent identity mismatch")
        if task.herdr is not None and started.workspace_id != task.herdr.workspace_id:
            raise LifecycleError("started implementer Agent workspace mismatch")
        if main.worktree is not None and started.cwd != Path(main.worktree):
            raise LifecycleError("started implementer Agent cwd mismatch")
        self._herdr.agent_prompt(name, self._initial_prompt(task_key, task))
        return AgentReference(name=name)

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
