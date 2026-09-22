"""Resolve persistent Agent definitions to available Herdr Panes."""

from typing import Protocol

from herdr_runtime import PaneInfo, WorkspaceInfo

from ..errors import AgentManagementError
from .config import AgentDefinition


class WorkspaceOperations(Protocol):
    def list(self) -> list[WorkspaceInfo]: ...


class PaneOperations(Protocol):
    def list(self, workspace_id: str) -> list[PaneInfo]: ...


class PaneResolutionOperations(Protocol):
    workspace: WorkspaceOperations
    pane: PaneOperations


def resolve_pane(
    definition: AgentDefinition,
    herdr: PaneResolutionOperations,
    occupied_pane_id: str | None = None,
) -> PaneInfo:
    """Return the one unoccupied Pane matching configured Workspace and cwd."""
    matching_workspaces = [
        item for item in herdr.workspace.list() if item.label == definition.workspace
    ]
    if not matching_workspaces:
        raise AgentManagementError(f"no Herdr workspace matches {definition.workspace}")
    if len(matching_workspaces) > 1:
        raise AgentManagementError(f"multiple Herdr workspaces match {definition.workspace}")
    panes = [
        pane
        for pane in herdr.pane.list(matching_workspaces[0].workspace_id)
        if pane.cwd == definition.cwd and (pane.agent is None or pane.pane_id == occupied_pane_id)
    ]
    if not panes:
        raise AgentManagementError(f"no available Pane matches Agent {definition.name}")
    if len(panes) > 1:
        raise AgentManagementError(f"multiple available Panes match Agent {definition.name}")
    return panes[0]
