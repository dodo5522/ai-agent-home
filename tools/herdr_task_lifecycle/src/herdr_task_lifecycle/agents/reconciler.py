"""Idempotent reconciliation of independently managed Herdr Agents."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from herdr_runtime import AgentInfo, HerdrError

from ..errors import LifecycleError
from .config import AgentDefinition


class AgentOperations(Protocol):
    """Herdr operations required by the Agent reconciler."""

    def agents(self) -> list[AgentInfo]:
        """Return the currently live Agents."""

    def agent_start(self, name: str, pane_id: str, kind: str = "codex") -> AgentInfo:
        """Start one named Agent on one Pane."""


@dataclass(frozen=True)
class AgentReconcileResult:
    """Summary of one independent Agent reconciliation pass."""

    started: tuple[str, ...]
    skipped: tuple[str, ...]
    failed: tuple[tuple[str, str], ...]


class AgentReconciler:
    """Start absent configured Agents without disturbing live Agents."""

    def __init__(
        self,
        herdr: AgentOperations,
        pane_resolver: Callable[[AgentDefinition], str],
    ) -> None:
        self._herdr = herdr
        self._pane_resolver = pane_resolver

    def reconcile(self, definitions: Sequence[AgentDefinition]) -> AgentReconcileResult:
        """Reconcile each definition by exact Agent name."""
        live_by_name = {agent.name: agent for agent in self._herdr.agents()}
        started: list[str] = []
        skipped: list[str] = []
        failed: list[tuple[str, str]] = []
        for definition in definitions:
            if definition.name in live_by_name:
                skipped.append(definition.name)
                continue
            try:
                pane_id = self._pane_resolver(definition)
                self._herdr.agent_start(definition.name, pane_id)
            except (LifecycleError, HerdrError) as error:
                failed.append((definition.name, str(error)))
                continue
            started.append(definition.name)
        return AgentReconcileResult(tuple(started), tuple(skipped), tuple(failed))
