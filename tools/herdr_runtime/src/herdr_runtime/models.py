"""Typed values returned by Herdr resource clients."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorkspaceInfo:
    workspace_id: str
    label: str


@dataclass(frozen=True)
class TabInfo:
    tab_id: str
    workspace_id: str
    label: str


@dataclass(frozen=True)
class PaneInfo:
    pane_id: str
    tab_id: str
    workspace_id: str | None = None
    cwd: Path | None = None
    agent: str | None = None


@dataclass(frozen=True)
class AgentInfo:
    name: str
    kind: str
    pane_id: str
    workspace_id: str
    cwd: Path


@dataclass(frozen=True)
class CreatedResources:
    workspace_id: str
    tab_id: str
    pane_id: str
