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
    CleanupOutcome,
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

    def _revalidate_target(
        self,
        task_key: TaskKey,
        action_name: CleanupActionName,
        target: str,
    ) -> CleanupOutcome:
        if action_name == "tab":
            return self._planner.revalidate_tab_target(task_key, target)
        if action_name == "worktree":
            return self._planner.revalidate_worktree_target(
                task_key, Path(target).resolve(strict=False)
            )
        return "delete"

    def _perform_target(
        self,
        task_key: TaskKey,
        action_name: CleanupActionName,
        target: str,
        task_root: Path,
    ) -> None:
        if self._revalidate_target(task_key, action_name, target) == "already_absent":
            return
        if action_name == "tab":
            self._herdr.tab_close(target)
        elif action_name == "worktree":
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
        else:
            self._remove_task_root(task_root)

    def _progress(
        self,
        task_root: Path,
        phase: str,
        completed: set[CleanupActionName],
        completed_targets: dict[CleanupActionName, set[str]],
    ) -> CleanupProgress:
        return CleanupProgress(
            phase=phase,
            completed_actions=completed,
            completed_targets={
                action: set(targets) for action, targets in completed_targets.items() if targets
            },
            task_root=str(task_root),
        )

    def _verify_completed_action(
        self,
        plan: CleanupPlan,
        action_name: CleanupActionName,
        task_root: Path,
    ) -> None:
        action = self._revalidate_action(plan, action_name)
        if action_name == "task_root":
            if action.outcome != "already_absent":
                raise LifecycleError("cleanup task_root completed target is live")
            return
        task = self._state.read_task(plan.task_key)
        for target in self._state_targets(action, task, task_root):
            if self._revalidate_target(plan.task_key, action_name, target) != "already_absent":
                raise LifecycleError(f"cleanup {action_name} completed target is live")

    def _record_failure(
        self,
        task_key: TaskKey,
        task_root: Path,
        completed: set[CleanupActionName],
        completed_targets: dict[CleanupActionName, set[str]],
    ) -> None:
        try:
            self._state.record_cleanup_progress(
                task_key,
                self._progress(task_root, "partial", completed, completed_targets),
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
            completed_targets: dict[CleanupActionName, set[str]] = {}
            phase = "pending"
        else:
            stored_root = Path(task.cleanup.task_root).resolve(strict=False)
            if stored_root != task_root:
                raise LifecycleError("stored cleanup root does not match --confirm-task-root")
            completed = set(task.cleanup.completed_actions)
            completed_targets = {
                action: set(targets) for action, targets in task.cleanup.completed_targets.items()
            }
            phase = task.cleanup.phase

        self._state.record_cleanup_progress(
            plan.task_key,
            self._progress(task_root, phase, completed, completed_targets),
        )

        current_action: CleanupActionName = "tab"
        try:
            for current_action in _ACTION_ORDER:
                if current_action in completed:
                    self._verify_completed_action(plan, current_action, task_root)
                    continue
                action = self._revalidate_action(plan, current_action)
                task = self._state.read_task(plan.task_key)
                targets = self._state_targets(action, task, task_root)
                action_targets = completed_targets.setdefault(current_action, set())
                for target in targets:
                    if target in action_targets:
                        if (
                            self._revalidate_target(plan.task_key, current_action, target)
                            != "already_absent"
                        ):
                            raise LifecycleError(
                                f"cleanup {current_action} completed target is live"
                            )
                        continue
                    self._perform_target(plan.task_key, current_action, target, task_root)
                    action_targets.add(target)
                    self._state.record_cleanup_progress(
                        plan.task_key,
                        self._progress(task_root, phase, completed, completed_targets),
                    )
                completed.add(current_action)
                self._state.record_cleanup_progress(
                    plan.task_key,
                    self._progress(task_root, phase, completed, completed_targets),
                )
            self._state.remove_task_after_cleanup(plan.task_key)
        except (LifecycleError, OSError) as error:
            self._record_failure(plan.task_key, task_root, completed, completed_targets)
            raise LifecycleError(f"cleanup {current_action} failed") from error

        return CleanupResult(plan.task_key, _ACTION_ORDER, mapping_removed=True)
