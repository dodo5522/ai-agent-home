"""Issue-start reconciliation workflow for Herdr-managed resources."""

import os
from dataclasses import dataclass
from pathlib import Path

from herdr_task_state.model import (
    HerdrReference,
    StateValidationError,
    Task,
    TaskKey,
    TaskState,
    Workstream,
)
from herdr_task_state.store import StateFilesystemError, StateStore

from .errors import TaskStartError
from .herdr import CreatedResources, HerdrClient, WorkspaceInfo, _HerdrOperations
from .identity import load_issue_title, resolve_repository, short_title
from .runner import CommandRunner, SubprocessRunner


@dataclass(frozen=True)
class TaskStartResolution:
    """Resolved task and managed Herdr IDs returned by task startup."""

    task: Task
    task_key: TaskKey
    workspace_id: str
    tab_id: str
    pane_id: str
    cwd: Path


class TaskStarter:
    """Reconcile managed Herdr resources for one Issue task."""

    def __init__(
        self,
        state_path: Path,
        runner: CommandRunner | None = None,
        herdr: _HerdrOperations | None = None,
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
