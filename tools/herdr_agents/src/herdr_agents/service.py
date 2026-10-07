"""Reusable exact-name Herdr Agent operations."""

from dataclasses import dataclass
from pathlib import Path
from time import monotonic, sleep
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
        native_args: tuple[str, ...] = (),
    ) -> None:
        self._herdr = herdr
        self._sessions = sessions
        self._inspector = inspector
        self._native_args = native_args

    @staticmethod
    def _same_owner(left: AgentBinding, right: AgentBinding) -> bool:
        """Compare stable session ownership while allowing Pane relocation."""
        return (
            left.name == right.name
            and left.repository == right.repository
            and left.workspace_id == right.workspace_id
            and left.workspace_label == right.workspace_label
            and left.worktree == right.worktree
            and left.branch == right.branch
        )

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
            mapping = (
                self._sessions.find_session(target.name) if self._sessions is not None else None
            )
            if mapping is not None:
                if not self._same_owner(mapping.binding, target.binding()):
                    raise AgentManagementError("Stored session binding does not match target")
            self._record(target, existing)
            return EnsuredAgent(existing, "live")
        mapping = self._sessions.find_session(target.name) if self._sessions is not None else None
        if mapping is not None:
            binding = target.binding()
            if not self._same_owner(mapping.binding, binding):
                raise AgentManagementError("Stored session binding does not match target")
            if self._inspector is not None and not self._inspector.is_usable(mapping.session_id):
                self._sessions.clear_session(target.name)
                started = self._start(target)
                self._validate(started, target)
                self._record(target, started)
                return EnsuredAgent(started, "fresh")
            try:
                started = self._herdr.start(
                    target.name,
                    target.pane_id,
                    native_args=(*self._native_args, "resume", mapping.session_id),
                )
            except HerdrRuntimeError:
                recovered = self._herdr.find(target.name)
                if recovered is None:
                    raise
                self._validate(recovered, target)
                if recovered.agent_session_id is None:
                    recovered = self.wait_for_session(
                        target, expected_session_id=mapping.session_id
                    )
                else:
                    if recovered.agent_session_id != mapping.session_id:
                        raise AgentManagementError("Resumed Agent has a different Codex session")
                    self._record(target, recovered)
                return EnsuredAgent(recovered, "resumed")
            self._validate(started, target)
            started = self._accept_resumed_session(started, mapping.session_id)
            self._record(target, started)
            return EnsuredAgent(started, "resumed")
        started = self._start(target)
        self._validate(started, target)
        self._record(target, started)
        return EnsuredAgent(started, "fresh")

    def _start(self, target: AgentTarget) -> AgentInfo:
        """Start an Agent, preserving the no-argument runtime call by default."""
        if self._native_args:
            return self._herdr.start(target.name, target.pane_id, native_args=self._native_args)
        return self._herdr.start(target.name, target.pane_id)

    @staticmethod
    def _accept_resumed_session(agent: AgentInfo, session_id: str) -> AgentInfo:
        """Associate a successful exact resume with its requested session ID.

        Codex does not currently rerun the SessionStart hook for ``codex resume``,
        so Herdr may omit the session ID from an otherwise successful start result.
        A reported different ID remains an error.
        """
        if agent.agent_session_id is not None and agent.agent_session_id != session_id:
            raise AgentManagementError("Resumed Agent has a different Codex session")
        return AgentInfo(
            agent.name,
            agent.kind,
            agent.pane_id,
            agent.workspace_id,
            agent.cwd,
            session_id,
        )

    def _record(self, target: AgentTarget, agent: AgentInfo) -> None:
        if self._sessions is None or agent.agent_session_id is None:
            return
        self._sessions.record_session(target.binding(), agent.agent_session_id)

    def wait_for_session(
        self,
        target: AgentTarget,
        timeout_seconds: float = 10.0,
        expected_session_id: str | None = None,
    ) -> AgentInfo:
        """Observe a started Agent until Codex exposes its session identity."""
        deadline = monotonic() + timeout_seconds
        while True:
            agent = self._herdr.find(target.name)
            if agent is None:
                raise AgentManagementError(
                    f"Agent {target.name} disappeared before session identity"
                )
            self._validate(agent, target)
            if agent.agent_session_id is not None:
                if (
                    expected_session_id is not None
                    and agent.agent_session_id != expected_session_id
                ):
                    raise AgentManagementError("Resumed Agent has a different Codex session")
                self._record(target, agent)
                return agent
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise AgentManagementError(f"Agent {target.name} has no Codex session identity")
            sleep(min(0.1, remaining))

    def prompt(self, name: str, text: str) -> None:
        """Send text to one exact managed Agent name."""
        self._herdr.prompt(name, text)
