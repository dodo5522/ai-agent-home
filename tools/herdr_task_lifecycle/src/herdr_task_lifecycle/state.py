"""Shared lifecycle task-state configuration."""

import os
from pathlib import Path

from herdr_task_state.model import CleanupProgress, StateValidationError, Task, TaskKey
from herdr_task_state.store import StateFilesystemError, StateStore

from .errors import LifecycleError


def state_path() -> Path:
    """Return the configured absolute lifecycle state-file path."""
    value = os.environ.get("HERDR_TASK_STATE_FILE")
    if value is None:
        value = os.path.join(
            os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")),
            "ai-agent-home",
            "herdr-tasks.json",
        )
    path = Path(value)
    if not path.is_absolute():
        raise LifecycleError(f"state path must be absolute: {path}")
    return path


class TaskStateRepository:
    """Read and atomically update lifecycle task state."""

    def __init__(self, path: Path) -> None:
        self._store = StateStore(path)

    def read_task(self, task_key: TaskKey) -> Task:
        """Return one validated task."""
        try:
            return self._store.get(str(task_key))
        except KeyError as error:
            raise LifecycleError(f"task is not present in state: {task_key}") from error
        except (StateFilesystemError, StateValidationError) as error:
            raise LifecycleError("cannot read task state") from error

    def record_cleanup_progress(self, task_key: TaskKey, progress: CleanupProgress) -> Task:
        """Atomically persist resumable cleanup progress on one task."""
        task = self.read_task(task_key)
        updated = task.model_copy(update={"cleanup": progress})
        try:
            return self._store.put(str(task_key), updated)
        except (StateFilesystemError, StateValidationError) as error:
            raise LifecycleError("cannot write cleanup progress") from error

    def remove_task_after_cleanup(self, task_key: TaskKey) -> None:
        """Atomically remove a task mapping after all cleanup actions complete."""
        try:
            self._store.remove(str(task_key))
        except (StateFilesystemError, StateValidationError) as error:
            raise LifecycleError("cannot remove cleaned task state") from error
