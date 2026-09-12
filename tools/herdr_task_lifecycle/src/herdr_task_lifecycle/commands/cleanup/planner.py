"""Read-only cleanup planning for stored Herdr task resources."""

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from herdr_task_state.model import Task, TaskKey

from ...errors import LifecycleError
from ...herdr import HerdrClient, _HerdrPlanningOperations
from ...runner import CommandRunner, SubprocessRunner
from ...state import TaskStateRepository

CleanupActionName = Literal["tab", "worktree", "task_root"]
CleanupOutcome = Literal["delete", "already_absent", "blocked"]
_TASKS_DIRECTORY = Path("/home/takashi/work/tasks")


@dataclass(frozen=True)
class CleanupActionPlan:
    """One validated cleanup action with a non-executable planning outcome."""

    action: CleanupActionName
    outcome: CleanupOutcome
    target: str
    reason: str


@dataclass(frozen=True)
class CleanupPlan:
    """Deterministic, immutable cleanup plan for one stored task."""

    task_key: TaskKey
    task_root: Path | None
    actions: tuple[CleanupActionPlan, CleanupActionPlan, CleanupActionPlan]

    def to_json(self) -> str:
        """Serialize the plan to stable human-reviewable JSON."""
        document = {
            "task_key": str(self.task_key),
            "task_root": str(self.task_root) if self.task_root is not None else None,
            "actions": [asdict(action) for action in self.actions],
        }
        return json.dumps(document, indent=2, ensure_ascii=False)


@dataclass(frozen=True)
class _GitWorktree:
    path: Path
    primary: bool


def _targets(values: list[str]) -> str:
    if len(values) == 1:
        return values[0]
    return json.dumps(values, ensure_ascii=False)


def _git_markers(root: Path) -> list[Path]:
    """Find Git markers without following symlinks or suppressing traversal errors."""
    markers: list[Path] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                if entry.name == ".git":
                    markers.append(path)
                elif entry.is_dir(follow_symlinks=False):
                    pending.append(path)
    return markers


class CleanupPlanner:
    """Validate state-recorded cleanup targets without mutating any resource."""

    def __init__(
        self,
        state_path: Path,
        repository_path: Path,
        *,
        runner: CommandRunner | None = None,
        herdr: _HerdrPlanningOperations | None = None,
        tasks_directory: Path = _TASKS_DIRECTORY,
    ) -> None:
        self._runner = runner or SubprocessRunner()
        self._herdr = herdr or HerdrClient(self._runner)
        self._state = TaskStateRepository(state_path)
        self._repository_path = repository_path
        self._tasks_directory = tasks_directory

    @staticmethod
    def _stored_tabs(task: Task) -> list[tuple[str, str]]:
        tabs: list[tuple[str, str]] = []
        for workstream_name in sorted(task.workstreams):
            workstream = task.workstreams[workstream_name]
            if workstream.tab_id is not None and workstream.tab_label is not None:
                tabs.append((workstream.tab_id, workstream.tab_label))
        return tabs

    def _plan_tabs(self, task: Task) -> CleanupActionPlan:
        tab_ids = [
            workstream.tab_id
            for workstream in task.workstreams.values()
            if workstream.tab_id is not None
        ]
        target = _targets(sorted(set(tab_ids))) if tab_ids else ""
        if any(
            workstream.tab_id is None or workstream.tab_label is None
            for workstream in task.workstreams.values()
        ):
            return CleanupActionPlan(
                "tab",
                "blocked",
                target,
                "stored Tab ID and label are required for every workstream",
            )
        if task.herdr is None or task.herdr.workspace_id is None:
            return CleanupActionPlan("tab", "blocked", target, "stored workspace ID is required")
        if task.herdr.workspace_label is None:
            return CleanupActionPlan("tab", "blocked", target, "stored workspace label is required")

        try:
            workspace = self._herdr.workspace_find(task.herdr.workspace_id)
            if workspace is None:
                for tab_id, _ in self._stored_tabs(task):
                    if self._herdr.tab_find(tab_id) is not None:
                        return CleanupActionPlan(
                            "tab",
                            "blocked",
                            target,
                            "stored workspace is absent but a stored Tab remains live",
                        )
                return CleanupActionPlan(
                    "tab", "already_absent", target, "stored workspace is no longer live"
                )
            if workspace.label != task.herdr.workspace_label:
                return CleanupActionPlan(
                    "tab",
                    "blocked",
                    target,
                    "live workspace label does not match stored workspace label",
                )

            live_count = 0
            for tab_id, tab_label in self._stored_tabs(task):
                tab = self._herdr.tab_find(tab_id)
                if tab is None:
                    continue
                live_count += 1
                if tab.workspace_id != workspace.workspace_id:
                    return CleanupActionPlan(
                        "tab",
                        "blocked",
                        target,
                        "live Tab workspace does not match stored workspace",
                    )
                if tab.label != tab_label:
                    return CleanupActionPlan(
                        "tab", "blocked", target, "live tab label does not match stored tab label"
                    )
        except LifecycleError:
            return CleanupActionPlan(
                "tab", "blocked", target, "live Herdr identity could not be validated"
            )

        if live_count == 0:
            return CleanupActionPlan(
                "tab", "already_absent", target, "stored Tabs are no longer live"
            )
        return CleanupActionPlan(
            "tab", "delete", target, "stored Tab matches its live workspace and label"
        )

    def _git_worktrees(self) -> tuple[list[_GitWorktree] | None, str | None]:
        result = self._runner.run(
            [
                "git",
                "-C",
                str(self._repository_path),
                "worktree",
                "list",
                "--porcelain",
            ]
        )
        if result.returncode != 0:
            return None, "Git worktree inventory could not be read"

        records: list[_GitWorktree] = []
        for block in result.stdout.split("\n\n"):
            lines = block.splitlines()
            if not lines:
                continue
            if not lines[0].startswith("worktree ") or len(lines[0]) == len("worktree "):
                return None, "Git worktree inventory is invalid"
            path = Path(lines[0][len("worktree ") :]).resolve(strict=False)
            records.append(_GitWorktree(path, primary=not records))
        if not records:
            return None, "Git worktree inventory is empty"
        return records, None

    @staticmethod
    def _stored_worktrees(task: Task) -> list[Path]:
        paths = {
            Path(workstream.worktree).resolve(strict=False)
            for workstream in task.workstreams.values()
            if workstream.worktree is not None
        }
        return sorted(paths, key=str)

    @staticmethod
    def _find_marked_root(worktree: Path) -> Path | None:
        for candidate in (worktree, *worktree.parents):
            marker = candidate / ".codex-task-root"
            if marker.is_file() and not marker.is_symlink():
                return candidate.resolve(strict=False)
        return None

    def _candidate_root(self, task: Task, worktrees: list[Path]) -> tuple[Path | None, str | None]:
        discovered_roots = [self._find_marked_root(path) for path in worktrees]
        if any(root is None for root in discovered_roots):
            return None, "every stored worktree must resolve to a direct .codex-task-root marker"
        roots = {root for root in discovered_roots if root is not None}
        if task.cleanup is not None:
            cleanup_root = Path(task.cleanup.task_root).resolve(strict=False)
            if roots and cleanup_root not in roots:
                return None, "stored cleanup root does not match worktree marker"
            roots.add(cleanup_root)
        if not roots:
            return None, "no direct .codex-task-root marker found from stored worktrees"
        if len(roots) != 1:
            return None, "stored worktrees resolve to different task roots"
        return roots.pop(), None

    @staticmethod
    def _registered_map(records: list[_GitWorktree]) -> dict[Path, _GitWorktree]:
        return {record.path: record for record in records}

    def _plan_worktrees(
        self,
        worktrees: list[Path],
        records: list[_GitWorktree] | None,
        inventory_error: str | None,
    ) -> CleanupActionPlan:
        target = _targets([str(path) for path in worktrees]) if worktrees else ""
        if not worktrees:
            return CleanupActionPlan(
                "worktree", "blocked", target, "no stored worktree path is available"
            )
        if records is None:
            return CleanupActionPlan("worktree", "blocked", target, inventory_error or "blocked")

        registered = self._registered_map(records)
        live_count = 0
        for path in worktrees:
            record = registered.get(path)
            if record is None:
                if path.exists() or path.is_symlink():
                    return CleanupActionPlan(
                        "worktree", "blocked", target, "stored path exists but is not registered"
                    )
                continue
            live_count += 1
            if record.primary:
                return CleanupActionPlan(
                    "worktree", "blocked", target, "stored path is the primary worktree"
                )
        if live_count == 0:
            return CleanupActionPlan(
                "worktree", "already_absent", target, "stored worktrees are no longer registered"
            )
        return CleanupActionPlan(
            "worktree", "delete", target, "stored path is a registered non-primary worktree"
        )

    def _plan_task_root(
        self,
        root: Path | None,
        root_error: str | None,
        worktrees: list[Path],
        records: list[_GitWorktree] | None,
        worktree_action: CleanupActionPlan,
    ) -> CleanupActionPlan:
        if root is None:
            return CleanupActionPlan(
                "task_root", "blocked", "", root_error or "task root is unknown"
            )
        target = str(root)
        tasks_directory = self._tasks_directory.resolve(strict=False)
        try:
            relative = root.relative_to(tasks_directory)
        except ValueError:
            return CleanupActionPlan(
                "task_root", "blocked", target, "task root is outside the tasks directory"
            )
        if relative == Path("."):
            return CleanupActionPlan(
                "task_root",
                "blocked",
                target,
                "task root must be strictly below the tasks directory",
            )
        if not root.exists() and not root.is_symlink():
            return CleanupActionPlan(
                "task_root", "already_absent", target, "stored task root is already absent"
            )
        marker = root / ".codex-task-root"
        if not marker.is_file() or marker.is_symlink():
            return CleanupActionPlan(
                "task_root",
                "blocked",
                target,
                "task root has no direct regular .codex-task-root marker",
            )
        if records is None:
            return CleanupActionPlan(
                "task_root", "blocked", target, "Git worktree inventory could not be validated"
            )
        if worktree_action.outcome == "blocked":
            return CleanupActionPlan(
                "task_root", "blocked", target, "stored worktree cleanup is blocked"
            )

        stored = set(worktrees)
        other = [
            record.path
            for record in records
            if record.path.is_relative_to(root) and record.path not in stored
        ]
        if other:
            return CleanupActionPlan(
                "task_root", "blocked", target, "task root contains another registered worktree"
            )
        try:
            unmanaged_git_markers = [
                marker
                for marker in _git_markers(root)
                if marker.parent.resolve(strict=False) not in stored
            ]
        except OSError:
            return CleanupActionPlan(
                "task_root", "blocked", target, "task root could not be scanned for Git worktrees"
            )
        if unmanaged_git_markers:
            return CleanupActionPlan(
                "task_root", "blocked", target, "task root contains an unmanaged Git worktree"
            )
        return CleanupActionPlan(
            "task_root",
            "delete",
            target,
            "task root is marked, contained, and has no unmanaged worktrees",
        )

    def plan(self, task_key: TaskKey) -> CleanupPlan:
        """Read and validate the three ordered cleanup targets for one task."""
        task = self._state.read_task(task_key)
        tab_action = self._plan_tabs(task)
        worktrees = self._stored_worktrees(task)
        records, inventory_error = self._git_worktrees()
        worktree_action = self._plan_worktrees(worktrees, records, inventory_error)
        root, root_error = self._candidate_root(task, worktrees)
        root_action = self._plan_task_root(root, root_error, worktrees, records, worktree_action)
        return CleanupPlan(task_key, root, (tab_action, worktree_action, root_action))
