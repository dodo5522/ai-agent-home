"""Shared lifecycle task-state configuration."""

import os
from pathlib import Path

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
