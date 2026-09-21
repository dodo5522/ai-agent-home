"""Independent reconciliation of persistent Agent definitions."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from herdr_runtime import HerdrRuntimeError, PaneInfo

from ..errors import AgentManagementError
from ..service import AgentManager, AgentTarget
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
        pane_resolver: Callable[[AgentDefinition], PaneInfo],
    ) -> None:
        self._manager = manager
        self._pane_resolver = pane_resolver

    def reconcile(self, definitions: Sequence[AgentDefinition]) -> AgentReconcileResult:
        """Reconcile every definition without stopping after one failure."""
        started: list[str] = []
        skipped: list[str] = []
        failed: list[tuple[str, str]] = []
        for definition in definitions:
            try:
                pane = self._pane_resolver(definition)
                if pane.workspace_id is None:
                    raise AgentManagementError(
                        f"Pane for Agent {definition.name} has no workspace identity"
                    )
                result = self._manager.ensure(
                    AgentTarget(
                        definition.name,
                        pane.pane_id,
                        pane.workspace_id,
                        definition.cwd,
                    )
                )
            except (AgentManagementError, HerdrRuntimeError) as error:
                failed.append((definition.name, str(error)))
                continue
            (started if result.started else skipped).append(definition.name)
        return AgentReconcileResult(tuple(started), tuple(skipped), tuple(failed))
