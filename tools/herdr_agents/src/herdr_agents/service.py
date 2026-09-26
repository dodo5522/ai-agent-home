"""Reusable exact-name Herdr Agent operations."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from herdr_runtime import AgentInfo, HerdrRuntimeError
from herdr_task_state.sessions import AgentBinding, SessionMapping

from .errors import AgentManagementError


class AgentOperations(Protocol):
    """Low-level Herdr operations required by AgentManager."""

    def find(self, name: str) -> AgentInfo | None: ...
    def start(
        self, name: str, pane_id: str, kind: str = "codex", native_args: tuple[str, ...] = ()
    ) -> AgentInfo: ...
    def prompt(self, name: str, text: str) -> None: ...


@dataclass(frozen=True)
class AgentTarget:
    """Expected identity and placement of one managed Agent."""

    name: str
    pane_id: str
    workspace_id: str
    cwd: Path
    workspace_label: str = ""
    repository: str = ""
    branch: str = ""

    def binding(self) -> AgentBinding:
        """Return the complete binding required for persistent session state."""
        if not self.workspace_label or not self.repository or not self.branch:
            raise AgentManagementError("Agent target has incomplete session binding")
        return AgentBinding(
            self.name,
            self.repository,
            self.workspace_id,
            self.workspace_label,
            self.cwd,
            self.branch,
            self.pane_id,
        )


@dataclass(frozen=True)
class EnsuredAgent:
    """Validated Agent and whether this call started it."""

    agent: AgentInfo
    disposition: Literal["live", "resumed", "fresh"]

    @property
    def started(self) -> bool:
        """Whether this reconciliation started a new Herdr Agent process."""
        return self.disposition != "live"


class SessionOperations(Protocol):
    def find_session(self, name: str) -> SessionMapping | None: ...
    def record_session(self, binding: AgentBinding, session_id: str) -> SessionMapping: ...
    def clear_session(self, name: str) -> None: ...


class SessionInspector(Protocol):
    def is_usable(self, session_id: str) -> bool: ...


class AgentManager:
    """Ensure and prompt exact-name Agents without lifecycle policy."""

    def __init__(
        self,
        herdr: AgentOperations,
        sessions: SessionOperations | None = None,
        inspector: SessionInspector | None = None,
    ) -> None:
        self._herdr = herdr
        self._sessions = sessions
        self._inspector = inspector

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
            self._record(target, existing)
            return EnsuredAgent(existing, "live")
        mapping = self._sessions.find_session(target.name) if self._sessions is not None else None
        if mapping is not None:
            binding = target.binding()
            if mapping.binding != binding:
                raise AgentManagementError("Stored session binding does not match target")
            if self._inspector is not None and not self._inspector.is_usable(mapping.session_id):
                self._sessions.clear_session(target.name)
                started = self._herdr.start(target.name, target.pane_id)
                self._validate(started, target)
                self._record(target, started)
                return EnsuredAgent(started, "fresh")
            try:
                started = self._herdr.start(
                    target.name, target.pane_id, native_args=("resume", mapping.session_id)
                )
            except HerdrRuntimeError:
                recovered = self._herdr.find(target.name)
                if recovered is None:
                    raise
                self._validate(recovered, target)
                if recovered.codex_session_id != mapping.session_id:
                    raise AgentManagementError("Resumed Agent has a different Codex session")
                self._record(target, recovered)
                return EnsuredAgent(recovered, "resumed")
            self._validate(started, target)
            if started.codex_session_id != mapping.session_id:
                raise AgentManagementError("Resumed Agent has a different Codex session")
            self._record(target, started)
            return EnsuredAgent(started, "resumed")
        started = self._herdr.start(target.name, target.pane_id)
        self._validate(started, target)
        self._record(target, started)
        return EnsuredAgent(started, "fresh")

    def _record(self, target: AgentTarget, agent: AgentInfo) -> None:
        if self._sessions is None:
            return
        if agent.codex_session_id is None:
            raise AgentManagementError("Codex Agent has no session identity")
        self._sessions.record_session(target.binding(), agent.codex_session_id)

    def prompt(self, name: str, text: str) -> None:
        """Send text to one exact managed Agent name."""
        self._herdr.prompt(name, text)
