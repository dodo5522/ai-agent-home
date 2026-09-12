"""Shared lifecycle task-state configuration."""

import os
from pathlib import Path

from herdr_task_state.model import StateValidationError, Task, TaskKey
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
    """Read lifecycle task state without creating locks or changing the state file."""

    def __init__(self, path: Path) -> None:
        self._store = StateStore(path)

    def read_task(self, task_key: TaskKey) -> Task:
        """Return one validated task while preserving a read-only planner boundary."""
        try:
            return self._store.get(str(task_key))
        except KeyError as error:
            raise LifecycleError(f"task is not present in state: {task_key}") from error
        except (StateFilesystemError, StateValidationError) as error:
            raise LifecycleError("cannot read task state") from error
