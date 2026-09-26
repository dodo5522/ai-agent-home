"""Independent reconciliation of persistent Agent definitions."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from herdr_runtime import AgentInfo, HerdrRuntimeError, PaneInfo

from ..bindings import GitBinding
from ..errors import AgentManagementError
from ..service import AgentManager, AgentOperations, AgentTarget
from .config import AgentDefinition


@dataclass(frozen=True)
class AgentReconcileResult:
    """Summary of one persistent Agent reconciliation pass."""

    started: tuple[str, ...]
    skipped: tuple[str, ...]
    failed: tuple[tuple[str, str], ...]


class AgentReconciler:
    """Ensure configured Agents independently by exact name."""

    def __init__(
        self,
        manager: AgentManager,
        agents: AgentOperations,
        pane_resolver: Callable[[AgentDefinition, AgentInfo | None], PaneInfo],
        binding_resolver: Callable[[Path], GitBinding] | None = None,
    ) -> None:
        self._manager = manager
        self._agents = agents
        self._pane_resolver = pane_resolver
        self._binding_resolver = binding_resolver

    def reconcile(self, definitions: Sequence[AgentDefinition]) -> AgentReconcileResult:
        """Reconcile every definition without stopping after one failure."""
        started: list[str] = []
        skipped: list[str] = []
        failed: list[tuple[str, str]] = []
        for definition in definitions:
            try:
                existing = self._agents.find(definition.name)
                pane = self._pane_resolver(definition, existing)
                if pane.workspace_id is None:
                    raise AgentManagementError(
                        f"Pane for Agent {definition.name} has no workspace identity"
                    )
                identity = None
                if self._binding_resolver is not None:
                    identity = self._binding_resolver(definition.cwd)
                result = self._manager.ensure(
                    AgentTarget(
                        definition.name,
                        pane.pane_id,
                        pane.workspace_id,
                        definition.cwd,
                        definition.workspace if identity is not None else "",
                        "" if identity is None else identity.repository,
                        "" if identity is None else identity.branch,
                    )
                )
            except (AgentManagementError, HerdrRuntimeError) as error:
                failed.append((definition.name, str(error)))
                continue
            (started if result.started else skipped).append(definition.name)
        return AgentReconcileResult(tuple(started), tuple(skipped), tuple(failed))
