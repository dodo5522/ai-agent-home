"""Typed Herdr CLI adapter for task startup."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from .errors import TaskStartError
from .runner import CommandRunner


@dataclass(frozen=True)
class WorkspaceInfo:
    """Identity fields returned for a Herdr workspace."""

    workspace_id: str
    label: str


@dataclass(frozen=True)
class TabInfo:
    """Identity fields returned for a Herdr tab."""

    tab_id: str
    workspace_id: str
    label: str


@dataclass(frozen=True)
class PaneInfo:
    """Identity fields returned for a Herdr pane."""

    pane_id: str
    tab_id: str


@dataclass(frozen=True)
class CreatedResources:
    """Opaque Herdr IDs returned when a workspace or tab is created."""

    workspace_id: str
    tab_id: str
    pane_id: str


class _HerdrOperations(Protocol):
    """Internal operations required by the task-start reconciler."""

    def workspace_get(self, workspace_id: str) -> WorkspaceInfo:
        """Fetch one workspace."""

    def workspace_create(self, label: str, cwd: Path) -> CreatedResources:
        """Create one workspace."""

    def workspace_close(self, workspace_id: str) -> None:
        """Close one workspace created by this invocation."""

    def tab_get(self, tab_id: str) -> TabInfo:
        """Fetch one tab."""

    def tab_create(self, workspace_id: str, label: str, cwd: Path) -> CreatedResources:
        """Create one tab."""

    def tab_rename(self, tab_id: str, label: str) -> TabInfo:
        """Rename one tab created by this invocation."""

    def tab_close(self, tab_id: str) -> None:
        """Close one tab created by this invocation."""

    def panes_for_workspace(self, workspace_id: str, tab_id: str) -> list[PaneInfo]:
        """List panes belonging to one tab."""


class HerdrClient(_HerdrOperations):
    """Typed adapter for the Herdr JSON CLI interface."""

    def __init__(self, runner: CommandRunner) -> None:
        self._runner = runner

    def _request(self, arguments: Sequence[str]) -> Mapping[str, object]:
        result = self._runner.run(["herdr", *arguments])
        if result.returncode != 0:
            raise TaskStartError(f"Herdr command failed: {arguments[0]}")
        try:
            document = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise TaskStartError("Herdr response is invalid JSON") from error
        if not isinstance(document, dict):
            raise TaskStartError("Herdr response is not an object")
        payload = document.get("result")
        if not isinstance(payload, dict):
            raise TaskStartError("Herdr response has no result object")
        return cast(Mapping[str, object], payload)

    @staticmethod
    def _member(payload: Mapping[str, object], name: str) -> Mapping[str, object]:
        value = payload.get(name)
        if not isinstance(value, dict):
            raise TaskStartError(f"Herdr response has no {name} object")
        return cast(Mapping[str, object], value)

    @staticmethod
    def _string(payload: Mapping[str, object], name: str) -> str:
        value = payload.get(name)
        if not isinstance(value, str) or not value:
            raise TaskStartError(f"Herdr response has no {name}")
        return value

    def workspace_get(self, workspace_id: str) -> WorkspaceInfo:
        """Fetch and validate one workspace identity."""
        workspace = self._member(self._request(["workspace", "get", workspace_id]), "workspace")
        actual_id = self._string(workspace, "workspace_id")
        if actual_id != workspace_id:
            raise TaskStartError("Herdr workspace identity mismatch")
        return WorkspaceInfo(actual_id, self._string(workspace, "label"))

    def workspace_create(self, label: str, cwd: Path) -> CreatedResources:
        """Create a background workspace and return its opaque resource IDs."""
        payload = self._request(
            ["workspace", "create", "--label", label, "--cwd", str(cwd), "--no-focus"]
        )
        workspace = self._member(payload, "workspace")
        tab = self._member(payload, "tab")
        pane = self._member(payload, "root_pane")
        workspace_id = self._string(workspace, "workspace_id")
        tab_id = self._string(tab, "tab_id")
        pane_id = self._string(pane, "pane_id")
        if (
            self._string(tab, "workspace_id") != workspace_id
            or self._string(pane, "tab_id") != tab_id
        ):
            raise TaskStartError("Herdr create response has inconsistent resource identities")
        return CreatedResources(workspace_id, tab_id, pane_id)

    def workspace_close(self, workspace_id: str) -> None:
        """Close a workspace created by this invocation during rollback."""
        self._request(["workspace", "close", workspace_id])

    def tab_get(self, tab_id: str) -> TabInfo:
        """Fetch and validate one tab identity."""
        tab = self._member(self._request(["tab", "get", tab_id]), "tab")
        actual_id = self._string(tab, "tab_id")
        if actual_id != tab_id:
            raise TaskStartError("Herdr tab identity mismatch")
        return TabInfo(actual_id, self._string(tab, "workspace_id"), self._string(tab, "label"))

    def tab_create(self, workspace_id: str, label: str, cwd: Path) -> CreatedResources:
        """Create a background tab with one root pane."""
        payload = self._request(
            [
                "tab",
                "create",
                "--workspace",
                workspace_id,
                "--cwd",
                str(cwd),
                "--label",
                label,
                "--no-focus",
            ]
        )
        tab = self._member(payload, "tab")
        pane = self._member(payload, "root_pane")
        tab_id = self._string(tab, "tab_id")
        pane_id = self._string(pane, "pane_id")
        if (
            self._string(tab, "workspace_id") != workspace_id
            or self._string(pane, "tab_id") != tab_id
        ):
            raise TaskStartError("Herdr create response has inconsistent resource identities")
        return CreatedResources(workspace_id, tab_id, pane_id)

    def tab_rename(self, tab_id: str, label: str) -> TabInfo:
        """Rename a tab created by this invocation and return its identity."""
        tab = self._member(self._request(["tab", "rename", tab_id, label]), "tab")
        actual_id = self._string(tab, "tab_id")
        if actual_id != tab_id or self._string(tab, "label") != label:
            raise TaskStartError("Herdr tab rename response has inconsistent identity")
        return TabInfo(actual_id, self._string(tab, "workspace_id"), label)

    def tab_close(self, tab_id: str) -> None:
        """Close a tab created by this invocation during rollback."""
        self._request(["tab", "close", tab_id])

    def panes_for_workspace(self, workspace_id: str, tab_id: str) -> list[PaneInfo]:
        """Return validated panes belonging to one tab in a workspace."""
        payload = self._request(["pane", "list", "--workspace", workspace_id])
        raw_panes = payload.get("panes")
        if not isinstance(raw_panes, list):
            raise TaskStartError("Herdr response has no panes list")
        panes: list[PaneInfo] = []
        for raw_pane in raw_panes:
            if not isinstance(raw_pane, dict):
                raise TaskStartError("Herdr pane response contains an invalid pane")
            pane = cast(Mapping[str, object], raw_pane)
            pane_info = PaneInfo(self._string(pane, "pane_id"), self._string(pane, "tab_id"))
            if pane_info.tab_id == tab_id:
                panes.append(pane_info)
        return panes
