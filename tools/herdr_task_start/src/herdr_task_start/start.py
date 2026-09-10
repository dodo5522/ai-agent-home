"""Repository, Issue, and Herdr reconciliation helpers for task startup."""

import json
import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from herdr_task_state.model import (
    HerdrReference,
    StateValidationError,
    Task,
    TaskKey,
    TaskState,
    Workstream,
)
from herdr_task_state.store import StateFilesystemError, StateStore


class TaskStartError(RuntimeError):
    """Raised when task-start input or an external command is invalid."""


@dataclass(frozen=True)
class CommandResult:
    """Captured result of one external command invocation."""

    returncode: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    """Interface for running external commands."""

    def run(self, arguments: Sequence[str], cwd: Path | None = None) -> CommandResult:
        """Run one command and capture its result."""


class SubprocessRunner:
    """Run commands through Python's subprocess API without a shell."""

    def run(self, arguments: Sequence[str], cwd: Path | None = None) -> CommandResult:
        """Run one command and capture stdout, stderr, and its exit status."""
        try:
            completed = subprocess.run(
                arguments,
                cwd=cwd,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as error:
            raise TaskStartError(f"cannot execute {arguments[0]}") from error
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)


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


class HerdrClient:
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


@dataclass(frozen=True)
class TaskStartResolution:
    """Resolved task and managed Herdr IDs returned by task startup."""

    task: Task
    task_key: TaskKey
    workspace_id: str
    tab_id: str
    pane_id: str
    cwd: Path


class HerdrOperations(Protocol):
    """Operations required by the task-start reconciler."""

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


class TaskStarter:
    """Reconcile managed Herdr resources for one Issue task."""

    def __init__(
        self,
        state_path: Path,
        runner: CommandRunner | None = None,
        herdr: HerdrOperations | None = None,
    ) -> None:
        self._runner = runner or SubprocessRunner()
        self._herdr = herdr or HerdrClient(self._runner)
        self._store = StateStore(state_path)

    def _read_state(self) -> TaskState:
        if not self._store.path.exists() and not self._store.path.is_symlink():
            return TaskState(version=1, tasks={})
        try:
            return self._store.read()
        except (StateFilesystemError, StateValidationError) as error:
            raise TaskStartError("cannot read task state") from error

    def _workspace_for_repository(
        self, state: TaskState, repository: str, cwd: Path
    ) -> tuple[str, CreatedResources | None]:
        candidates = sorted(
            {
                task.herdr.workspace_id
                for task in state.tasks.values()
                if task.repository == repository and task.herdr and task.herdr.workspace_id
            }
        )
        valid: list[WorkspaceInfo] = []
        for workspace_id in candidates:
            try:
                workspace = self._herdr.workspace_get(workspace_id)
            except TaskStartError:
                continue
            if workspace.label == repository:
                valid.append(workspace)
        if len(valid) > 1:
            raise TaskStartError("multiple managed workspaces match repository")
        if valid:
            return valid[0].workspace_id, None
        created = self._herdr.workspace_create(repository, cwd)
        return created.workspace_id, created

    def _validate_existing_tab(
        self,
        task: Task | None,
        workspace_id: str,
        label: str,
    ) -> tuple[str, str] | None:
        if task is None:
            return None
        tab_id = task.workstreams["main"].tab_id
        if tab_id is None:
            return None
        try:
            tab = self._herdr.tab_get(tab_id)
        except TaskStartError:
            return None
        if tab.workspace_id != workspace_id or tab.label != label:
            return None
        panes = self._herdr.panes_for_workspace(workspace_id, tab_id)
        if len(panes) != 1:
            raise TaskStartError("managed tab must contain exactly one pane")
        stored_pane_id = (task.workstreams["main"].pane_ids or {}).get("root")
        if stored_pane_id is not None and panes[0].pane_id != stored_pane_id:
            return None
        return tab_id, panes[0].pane_id

    def _validate_created_tab(
        self, workspace_id: str, created: CreatedResources
    ) -> tuple[str, str]:
        panes = self._herdr.panes_for_workspace(workspace_id, created.tab_id)
        if len(panes) != 1 or panes[0].pane_id != created.pane_id:
            raise TaskStartError("created tab must contain exactly one root pane")
        return created.tab_id, created.pane_id

    def start(self, issue_number: int, cwd: Path) -> TaskStartResolution:
        """Resolve an Issue and reconcile its managed Herdr resources."""
        if os.environ.get("HERDR_ENV") != "1":
            raise TaskStartError("HERDR_ENV=1 is required")
        if issue_number <= 0:
            raise TaskStartError("Issue number must be positive")
        if not cwd.is_absolute() or not cwd.is_dir():
            raise TaskStartError("cwd must be an absolute directory")

        repository = resolve_repository(cwd, self._runner)
        title = load_issue_title(repository, issue_number, self._runner)
        task_key = TaskKey(repository, issue_number)
        tab_label = f"{issue_number} {short_title(title)}"
        state = self._read_state()
        current = state.tasks.get(str(task_key))
        created_workspace_id: str | None = None
        created_tab_id: str | None = None
        try:
            workspace_id, created_workspace = self._workspace_for_repository(state, repository, cwd)
            if created_workspace is not None:
                created_workspace_id = workspace_id
                renamed = self._herdr.tab_rename(created_workspace.tab_id, tab_label)
                if renamed.workspace_id != workspace_id or renamed.label != tab_label:
                    raise TaskStartError("created tab identity mismatch")
                tab_id, pane_id = self._validate_created_tab(workspace_id, created_workspace)
            else:
                existing = self._validate_existing_tab(current, workspace_id, tab_label)
                if existing is None:
                    created = self._herdr.tab_create(workspace_id, tab_label, cwd)
                    created_tab_id = created.tab_id
                    tab_id, pane_id = self._validate_created_tab(workspace_id, created)
                else:
                    tab_id, pane_id = existing

            if current is None:
                task = Task(
                    repository=repository,
                    issue_number=issue_number,
                    title=title,
                    herdr=HerdrReference(
                        workspace_id=workspace_id,
                        workspace_label=repository,
                    ),
                    workstreams={"main": Workstream()},
                )
            else:
                task = current.model_copy(update={"title": title})
            main = task.workstreams["main"]
            pane_ids = {**(main.pane_ids or {}), "root": pane_id}
            updated_main = main.model_copy(
                update={"tab_id": tab_id, "tab_label": tab_label, "pane_ids": pane_ids}
            )
            updated = task.model_copy(
                update={
                    "herdr": HerdrReference(
                        workspace_id=workspace_id,
                        workspace_label=repository,
                    ),
                    "workstreams": {**task.workstreams, "main": updated_main},
                }
            )
            stored = self._store.put(str(task_key), updated)
            return TaskStartResolution(stored, task_key, workspace_id, tab_id, pane_id, cwd)
        except Exception:
            if created_workspace_id is not None:
                try:
                    self._herdr.workspace_close(created_workspace_id)
                except TaskStartError:
                    pass
            elif created_tab_id is not None:
                try:
                    self._herdr.tab_close(created_tab_id)
                except TaskStartError:
                    pass
            raise


_GITHUB_REMOTE_RE = re.compile(
    r"^(?:https://github\.com/|git@github\.com:)([A-Za-z0-9][A-Za-z0-9._-]*)/"
    r"([A-Za-z0-9][A-Za-z0-9._-]*?)(?:\.git)?$"
)


def resolve_repository(cwd: Path, runner: CommandRunner) -> str:
    """Resolve the normalized GitHub owner/name from the origin remote."""
    result = runner.run(["git", "-C", str(cwd), "remote", "get-url", "origin"])
    if result.returncode != 0:
        raise TaskStartError("cannot resolve GitHub remote")
    match = _GITHUB_REMOTE_RE.fullmatch(result.stdout.strip())
    if match is None:
        raise TaskStartError("origin is not a supported GitHub remote")
    return f"{match.group(1).lower()}/{match.group(2).lower()}"


def load_issue_title(repository: str, issue_number: int, runner: CommandRunner) -> str:
    """Load one non-empty Issue title from GitHub CLI JSON output."""
    result = runner.run(
        [
            "gh",
            "issue",
            "view",
            str(issue_number),
            "--repo",
            repository,
            "--json",
            "title",
        ]
    )
    if result.returncode != 0:
        raise TaskStartError("cannot load GitHub Issue title")
    try:
        document = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise TaskStartError("GitHub Issue title response is invalid JSON") from error
    if not isinstance(document, dict) or not isinstance(document.get("title"), str):
        raise TaskStartError("GitHub Issue title response is invalid")
    title = document["title"]
    if not title.strip():
        raise TaskStartError("GitHub Issue title is empty")
    return title


def short_title(title: str) -> str:
    """Normalize an Issue title to a deterministic 60-character label."""
    normalized = " ".join(title.split())
    if len(normalized) <= 60:
        return normalized
    return normalized[:59] + "…"
