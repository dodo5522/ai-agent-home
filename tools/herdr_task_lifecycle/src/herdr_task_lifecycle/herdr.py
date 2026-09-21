"""Typed Herdr CLI adapter for task lifecycle operations."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from .errors import LifecycleError
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
    workspace_id: str | None = None
    cwd: Path | None = None
    agent: str | None = None


@dataclass(frozen=True)
class AgentInfo:
    """Identity fields returned for a live Herdr Agent."""

    name: str
    kind: str
    pane_id: str
    workspace_id: str
    cwd: Path


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

    def workspaces(self) -> list[WorkspaceInfo]:
        """List workspaces."""

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

    def agents(self) -> list[AgentInfo]:
        """List live Agents with validated identity fields."""

    def panes(self, workspace_id: str) -> list[PaneInfo]:
        """List panes in one workspace."""

    def pane_get(self, pane_id: str) -> PaneInfo:
        """Fetch one pane with validated identity fields."""

    def agent_start(self, name: str, pane_id: str, kind: str = "codex") -> AgentInfo:
        """Start one named Agent on an explicit pane."""

    def agent_prompt(self, name: str, text: str) -> None:
        """Send text to one named Agent."""


class _HerdrPlanningOperations(Protocol):
    """Read-only Herdr operations required by cleanup planning."""

    def workspace_find(self, workspace_id: str) -> WorkspaceInfo | None:
        """Return the exact live workspace, or None when it is absent."""

    def tab_find(self, tab_id: str) -> TabInfo | None:
        """Return the exact live tab, or None when it is absent."""


class HerdrClient(_HerdrOperations, _HerdrPlanningOperations):
    """Typed adapter for the Herdr JSON CLI interface."""

    def __init__(self, runner: CommandRunner, herdr_bin: str = "herdr") -> None:
        self._runner = runner
        self._herdr_bin = herdr_bin

    def _request(self, arguments: Sequence[str]) -> Mapping[str, object]:
        result = self._runner.run([self._herdr_bin, *arguments])
        if result.returncode != 0:
            raise LifecycleError(f"Herdr command failed: {arguments[0]}")
        try:
            document = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise LifecycleError("Herdr response is invalid JSON") from error
        if not isinstance(document, dict):
            raise LifecycleError("Herdr response is not an object")
        payload = document.get("result")
        if not isinstance(payload, dict):
            raise LifecycleError("Herdr response has no result object")
        return cast(Mapping[str, object], payload)

    @staticmethod
    def _member(payload: Mapping[str, object], name: str) -> Mapping[str, object]:
        value = payload.get(name)
        if not isinstance(value, dict):
            raise LifecycleError(f"Herdr response has no {name} object")
        return cast(Mapping[str, object], value)

    @staticmethod
    def _string(payload: Mapping[str, object], name: str) -> str:
        value = payload.get(name)
        if not isinstance(value, str) or not value:
            raise LifecycleError(f"Herdr response has no {name}")
        return value

    def workspace_get(self, workspace_id: str) -> WorkspaceInfo:
        """Fetch and validate one workspace identity."""
        workspace = self._member(self._request(["workspace", "get", workspace_id]), "workspace")
        actual_id = self._string(workspace, "workspace_id")
        if actual_id != workspace_id:
            raise LifecycleError("Herdr workspace identity mismatch")
        return WorkspaceInfo(actual_id, self._string(workspace, "label"))

    def workspaces(self) -> list[WorkspaceInfo]:
        """Return validated live workspaces."""
        payload = self._request(["workspace", "list"])
        raw_workspaces = payload.get("workspaces")
        if not isinstance(raw_workspaces, list):
            raise LifecycleError("Herdr response has no workspaces list")
        workspaces: list[WorkspaceInfo] = []
        for raw_workspace in raw_workspaces:
            if not isinstance(raw_workspace, dict):
                raise LifecycleError("Herdr workspace response contains an invalid workspace")
            workspace = cast(Mapping[str, object], raw_workspace)
            workspaces.append(
                WorkspaceInfo(
                    self._string(workspace, "workspace_id"),
                    self._string(workspace, "label"),
                )
            )
        return workspaces

    def workspace_find(self, workspace_id: str) -> WorkspaceInfo | None:
        """Find one workspace by opaque ID without inferring ownership from labels."""
        payload = self._request(["workspace", "list"])
        raw_workspaces = payload.get("workspaces")
        if not isinstance(raw_workspaces, list):
            raise LifecycleError("Herdr response has no workspaces list")
        for raw_workspace in raw_workspaces:
            if not isinstance(raw_workspace, dict):
                raise LifecycleError("Herdr workspace response contains an invalid workspace")
            workspace = cast(Mapping[str, object], raw_workspace)
            actual_id = self._string(workspace, "workspace_id")
            if actual_id == workspace_id:
                return WorkspaceInfo(actual_id, self._string(workspace, "label"))
        return None

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
            raise LifecycleError("Herdr create response has inconsistent resource identities")
        return CreatedResources(workspace_id, tab_id, pane_id)

    def workspace_close(self, workspace_id: str) -> None:
        """Close a workspace created by this invocation during rollback."""
        self._request(["workspace", "close", workspace_id])

    def tab_get(self, tab_id: str) -> TabInfo:
        """Fetch and validate one tab identity."""
        tab = self._member(self._request(["tab", "get", tab_id]), "tab")
        actual_id = self._string(tab, "tab_id")
        if actual_id != tab_id:
            raise LifecycleError("Herdr tab identity mismatch")
        return TabInfo(actual_id, self._string(tab, "workspace_id"), self._string(tab, "label"))

    def tab_find(self, tab_id: str) -> TabInfo | None:
        """Find one tab by opaque ID without inferring ownership from labels."""
        payload = self._request(["tab", "list"])
        raw_tabs = payload.get("tabs")
        if not isinstance(raw_tabs, list):
            raise LifecycleError("Herdr response has no tabs list")
        for raw_tab in raw_tabs:
            if not isinstance(raw_tab, dict):
                raise LifecycleError("Herdr tab response contains an invalid tab")
            tab = cast(Mapping[str, object], raw_tab)
            actual_id = self._string(tab, "tab_id")
            if actual_id == tab_id:
                return TabInfo(
                    actual_id,
                    self._string(tab, "workspace_id"),
                    self._string(tab, "label"),
                )
        return None

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
            raise LifecycleError("Herdr create response has inconsistent resource identities")
        return CreatedResources(workspace_id, tab_id, pane_id)

    def tab_rename(self, tab_id: str, label: str) -> TabInfo:
        """Rename a tab created by this invocation and return its identity."""
        tab = self._member(self._request(["tab", "rename", tab_id, label]), "tab")
        actual_id = self._string(tab, "tab_id")
        if actual_id != tab_id or self._string(tab, "label") != label:
            raise LifecycleError("Herdr tab rename response has inconsistent identity")
        return TabInfo(actual_id, self._string(tab, "workspace_id"), label)

    def tab_close(self, tab_id: str) -> None:
        """Close a tab created by this invocation during rollback."""
        self._request(["tab", "close", tab_id])

    def _pane_info(self, pane: Mapping[str, object]) -> PaneInfo:
        cwd_value = pane.get("cwd")
        cwd = None
        if cwd_value is not None:
            cwd_text = self._string(cast(Mapping[str, object], {"cwd": cwd_value}), "cwd")
            cwd = Path(cwd_text)
        workspace_value = pane.get("workspace_id")
        workspace_id = workspace_value if isinstance(workspace_value, str) else None
        agent_value = pane.get("agent")
        agent = agent_value if isinstance(agent_value, str) else None
        return PaneInfo(
            self._string(pane, "pane_id"),
            self._string(pane, "tab_id"),
            workspace_id,
            cwd,
            agent,
        )

    def panes(self, workspace_id: str) -> list[PaneInfo]:
        """Return validated panes belonging to one workspace."""
        payload = self._request(["pane", "list", "--workspace", workspace_id])
        raw_panes = payload.get("panes")
        if not isinstance(raw_panes, list):
            raise LifecycleError("Herdr response has no panes list")
        panes: list[PaneInfo] = []
        for raw_pane in raw_panes:
            if not isinstance(raw_pane, dict):
                raise LifecycleError("Herdr pane response contains an invalid pane")
            pane = self._pane_info(cast(Mapping[str, object], raw_pane))
            if pane.workspace_id is not None and pane.workspace_id != workspace_id:
                raise LifecycleError("Herdr pane workspace identity mismatch")
            panes.append(pane)
        return panes

    def panes_for_workspace(self, workspace_id: str, tab_id: str) -> list[PaneInfo]:
        """Return validated panes belonging to one tab in a workspace."""
        return [pane for pane in self.panes(workspace_id) if pane.tab_id == tab_id]

    def pane_get(self, pane_id: str) -> PaneInfo:
        """Fetch one pane with validated identity fields."""
        pane = self._member(self._request(["pane", "get", pane_id]), "pane")
        actual_id = self._string(pane, "pane_id")
        if actual_id != pane_id:
            raise LifecycleError("Herdr pane identity mismatch")
        return self._pane_info(pane)

    def _agent_info(self, agent: Mapping[str, object]) -> AgentInfo:
        session = agent.get("agent_session")
        kind = "codex"
        if isinstance(session, dict) and isinstance(session.get("agent"), str):
            kind = self._string(cast(Mapping[str, object], session), "agent")
        cwd_text = self._string(agent, "cwd")
        return AgentInfo(
            name=self._string(agent, "agent"),
            kind=kind,
            pane_id=self._string(agent, "pane_id"),
            workspace_id=self._string(agent, "workspace_id"),
            cwd=Path(cwd_text),
        )

    def agents(self) -> list[AgentInfo]:
        """Return validated live Agents."""
        payload = self._request(["agent", "list"])
        raw_agents = payload.get("agents")
        if not isinstance(raw_agents, list):
            raise LifecycleError("Herdr response has no agents list")
        agents: list[AgentInfo] = []
        for raw_agent in raw_agents:
            if not isinstance(raw_agent, dict):
                raise LifecycleError("Herdr Agent response contains an invalid Agent")
            agents.append(self._agent_info(cast(Mapping[str, object], raw_agent)))
        return agents

    def agent_start(self, name: str, pane_id: str, kind: str = "codex") -> AgentInfo:
        """Start one Agent on one explicit pane and validate its identity."""
        payload = self._request(
            ["agent", "start", name, "--kind", kind, "--pane", pane_id]
        )
        agent = self._agent_info(self._member(payload, "agent"))
        if agent.name != name or agent.pane_id != pane_id or agent.kind != kind:
            raise LifecycleError("Herdr Agent start response has inconsistent identity")
        return agent

    def agent_prompt(self, name: str, text: str) -> None:
        """Send one prompt to an exact Agent name."""
        self._request(["agent", "prompt", name, text])
