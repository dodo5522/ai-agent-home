"""Exceptions raised while starting a Herdr-managed Issue task."""


class TaskStartError(RuntimeError):
    """Raised when task-start input or an external command is invalid."""
