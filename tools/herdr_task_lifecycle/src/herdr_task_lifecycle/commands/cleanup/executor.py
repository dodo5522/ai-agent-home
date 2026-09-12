"""Validated, resumable execution of planned task cleanup."""

import json
import shutil
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from herdr_task_state.model import CleanupProgress, Task, TaskKey

from ...errors import LifecycleError
from ...herdr import HerdrClient, _HerdrPlanningOperations
from ...runner import CommandRunner, SubprocessRunner
from ...state import TaskStateRepository
from .planner import (
    _TASKS_DIRECTORY,
    CleanupActionName,
    CleanupActionPlan,
    CleanupPlan,
    CleanupPlanner,
)

_ACTION_ORDER: tuple[CleanupActionName, ...] = ("tab", "worktree", "task_root")


class _HerdrCleanupOperations(_HerdrPlanningOperations, Protocol):
    """Herdr operations needed to validate and execute Tab cleanup."""

    def tab_close(self, tab_id: str) -> None:
        """Close one exact validated Tab ID."""


@dataclass(frozen=True)
class CleanupResult:
    """Normalized outcome of a completed cleanup execution."""

    task_key: TaskKey
    completed_actions: tuple[CleanupActionName, ...]
    mapping_removed: bool

    def to_json(self) -> str:
        """Serialize the result to stable machine-readable JSON."""
        document = asdict(self)
        document["task_key"] = str(self.task_key)
        document["completed_actions"] = list(self.completed_actions)
        return json.dumps(document, indent=2, ensure_ascii=False)


def _display_target(values: tuple[str, ...]) -> str:
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    return json.dumps(list(values), ensure_ascii=False)


class CleanupExecutor:
    """Execute an approved cleanup plan with validation before every action."""

    def __init__(
        self,
        state_path: Path,
        repository_path: Path,
        *,
        runner: CommandRunner | None = None,
        herdr: _HerdrCleanupOperations | None = None,
        tasks_directory: Path = _TASKS_DIRECTORY,
        remove_task_root: Callable[[Path], None] = shutil.rmtree,
        state_repository: TaskStateRepository | None = None,
    ) -> None:
        self._runner = runner or SubprocessRunner()
        self._herdr = herdr or HerdrClient(self._runner)
        self._planner = CleanupPlanner(
            state_path,
            repository_path,
            runner=self._runner,
            herdr=self._herdr,
            tasks_directory=tasks_directory,
        )
        self._state = state_repository or TaskStateRepository(state_path)
        self._repository_path = repository_path
        self._remove_task_root = remove_task_root

    @staticmethod
    def _validate_confirmation(plan: CleanupPlan, confirmed_task_root: Path) -> Path:
        confirmed = confirmed_task_root.resolve(strict=False)
        if (
            not confirmed_task_root.is_absolute()
            or confirmed_task_root != confirmed
            or plan.task_root is None
            or plan.task_root != confirmed
        ):
            raise LifecycleError("--confirm-task-root must exactly match the resolved planned root")
        return confirmed

    @staticmethod
    def _validate_plan_shape(plan: CleanupPlan) -> None:
        if tuple(action.action for action in plan.actions) != _ACTION_ORDER:
            raise LifecycleError("cleanup plan has an invalid action order")
        blocked = [action.action for action in plan.actions if action.outcome == "blocked"]
        if blocked:
            raise LifecycleError(f"cleanup plan is blocked at {blocked[0]}")

    def _revalidate_action(
        self, approved: CleanupPlan, action_name: CleanupActionName
    ) -> CleanupActionPlan:
        current = self._planner.plan(approved.task_key)
        self._validate_plan_shape(current)
        if current.task_root != approved.task_root:
            raise LifecycleError(f"cleanup {action_name} revalidation changed the task root")
        approved_action = next(
            action for action in approved.actions if action.action == action_name
        )
        current_action = next(action for action in current.actions if action.action == action_name)
        if current_action.target != approved_action.target:
            raise LifecycleError(f"cleanup {action_name} revalidation changed the target")
        return current_action

    @staticmethod
    def _state_targets(action: CleanupActionPlan, task: Task, task_root: Path) -> tuple[str, ...]:
        if action.action == "tab":
            targets = tuple(
                sorted(
                    {
                        workstream.tab_id
                        for workstream in task.workstreams.values()
                        if workstream.tab_id is not None
                    }
                )
            )
        elif action.action == "worktree":
            targets = tuple(
                str(path)
                for path in sorted(
                    {
                        Path(workstream.worktree).resolve(strict=False)
                        for workstream in task.workstreams.values()
                        if workstream.worktree is not None
                    },
                    key=str,
                )
            )
        else:
            targets = (str(task_root),)
        if _display_target(targets) != action.target:
            raise LifecycleError(f"cleanup {action.action} state changed after revalidation")
        return targets

    def _close_tabs(self, tab_ids: tuple[str, ...]) -> None:
        for tab_id in tab_ids:
            self._herdr.tab_close(tab_id)

    def _remove_worktrees(self, targets: tuple[str, ...]) -> None:
        for target in targets:
            result = self._runner.run(
                [
                    "git",
                    "-C",
                    str(self._repository_path),
                    "worktree",
                    "remove",
                    target,
                ]
            )
            if result.returncode != 0:
                raise LifecycleError("Git worktree removal failed")

    def _perform_action(
        self, task_key: TaskKey, action: CleanupActionPlan, task_root: Path
    ) -> None:
        task = self._state.read_task(task_key)
        targets = self._state_targets(action, task, task_root)
        if action.outcome == "already_absent":
            return
        if action.action == "tab":
            self._close_tabs(targets)
        elif action.action == "worktree":
            self._remove_worktrees(targets)
        else:
            self._remove_task_root(task_root)

    def _record_failure(
        self,
        task_key: TaskKey,
        task_root: Path,
        completed: set[CleanupActionName],
    ) -> None:
        if not completed:
            return
        try:
            self._state.record_cleanup_progress(
                task_key,
                CleanupProgress(
                    phase="partial",
                    completed_actions=completed,
                    task_root=str(task_root),
                ),
            )
        except LifecycleError:
            pass

    def execute(self, plan: CleanupPlan, confirmed_task_root: Path) -> CleanupResult:
        """Execute exactly one validated plan and remove its state mapping when complete."""
        task_root = self._validate_confirmation(plan, confirmed_task_root)
        self._validate_plan_shape(plan)
        task = self._state.read_task(plan.task_key)
        if task.cleanup is None:
            completed: set[CleanupActionName] = set()
            phase = "pending"
        else:
            stored_root = Path(task.cleanup.task_root).resolve(strict=False)
            if stored_root != task_root:
                raise LifecycleError("stored cleanup root does not match --confirm-task-root")
            completed = set(task.cleanup.completed_actions)
            phase = task.cleanup.phase

        self._state.record_cleanup_progress(
            plan.task_key,
            CleanupProgress(
                phase=phase,
                completed_actions=completed,
                task_root=str(task_root),
            ),
        )

        current_action: CleanupActionName = "tab"
        try:
            for current_action in _ACTION_ORDER:
                if current_action in completed:
                    continue
                action = self._revalidate_action(plan, current_action)
                self._perform_action(plan.task_key, action, task_root)
                completed.add(current_action)
                self._state.record_cleanup_progress(
                    plan.task_key,
                    CleanupProgress(
                        phase=phase,
                        completed_actions=completed,
                        task_root=str(task_root),
                    ),
                )
            self._state.remove_task_after_cleanup(plan.task_key)
        except (LifecycleError, OSError) as error:
            self._record_failure(plan.task_key, task_root, completed)
            raise LifecycleError(f"cleanup {current_action} failed") from error

        return CleanupResult(plan.task_key, _ACTION_ORDER, mapping_removed=True)
