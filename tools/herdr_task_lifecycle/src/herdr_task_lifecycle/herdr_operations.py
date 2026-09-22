"""Herdr resource protocols required by task lifecycle policy."""

from pathlib import Path
from typing import Protocol

from herdr_runtime import CreatedResources, PaneInfo, TabInfo, WorkspaceInfo


class WorkspaceOperations(Protocol):
    def get(self, workspace_id: str) -> WorkspaceInfo: ...
    def find(self, workspace_id: str) -> WorkspaceInfo | None: ...
    def create(self, label: str, cwd: Path) -> CreatedResources: ...
    def close(self, workspace_id: str) -> None: ...


class TabOperations(Protocol):
    def get(self, tab_id: str) -> TabInfo: ...
    def find(self, tab_id: str) -> TabInfo | None: ...
    def create(self, workspace_id: str, label: str, cwd: Path) -> CreatedResources: ...
    def rename(self, tab_id: str, label: str) -> TabInfo: ...
    def close(self, tab_id: str) -> None: ...


class PaneOperations(Protocol):
    def for_tab(self, workspace_id: str, tab_id: str) -> list[PaneInfo]: ...


class HerdrOperations(Protocol):
    workspace: WorkspaceOperations
    tab: TabOperations
    pane: PaneOperations


class HerdrPlanningOperations(Protocol):
    workspace: WorkspaceOperations
    tab: TabOperations
