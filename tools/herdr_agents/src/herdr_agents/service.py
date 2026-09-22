"""Reusable exact-name Herdr Agent operations."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from herdr_runtime import AgentInfo

from .errors import AgentManagementError


class AgentOperations(Protocol):
    """Low-level Herdr operations required by AgentManager."""

    def find(self, name: str) -> AgentInfo | None: ...
    def start(self, name: str, pane_id: str, kind: str = "codex") -> AgentInfo: ...
    def prompt(self, name: str, text: str) -> None: ...


@dataclass(frozen=True)
class AgentTarget:
    """Expected identity and placement of one managed Agent."""

    name: str
    pane_id: str
    workspace_id: str
    cwd: Path


@dataclass(frozen=True)
class EnsuredAgent:
    """Validated Agent and whether this call started it."""

    agent: AgentInfo
    started: bool


class AgentManager:
    """Ensure and prompt exact-name Agents without lifecycle policy."""

    def __init__(self, herdr: AgentOperations) -> None:
        self._herdr = herdr

    @staticmethod
    def _validate(agent: AgentInfo, target: AgentTarget) -> None:
        if agent.name != target.name:
            raise AgentManagementError("Agent name does not match target")
        if agent.pane_id != target.pane_id:
            raise AgentManagementError(f"Agent {target.name} is on a different pane")
        if agent.workspace_id != target.workspace_id:
            raise AgentManagementError(f"Agent {target.name} is in a different workspace")
        if agent.cwd != target.cwd:
            raise AgentManagementError(f"Agent {target.name} has a different cwd")

    def ensure(self, target: AgentTarget) -> EnsuredAgent:
        """Return the exact live Agent, starting it when absent."""
        existing = self._herdr.find(target.name)
        if existing is not None:
            self._validate(existing, target)
            return EnsuredAgent(existing, started=False)
        started = self._herdr.start(target.name, target.pane_id)
        self._validate(started, target)
        return EnsuredAgent(started, started=True)

    def prompt(self, name: str, text: str) -> None:
        """Send text to one exact managed Agent name."""
        self._herdr.prompt(name, text)
