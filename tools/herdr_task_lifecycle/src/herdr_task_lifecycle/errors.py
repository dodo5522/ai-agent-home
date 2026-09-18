"""Shared public errors and process exit statuses for lifecycle commands."""

from enum import IntEnum


class ExitCode(IntEnum):
    """Stable process exit statuses exposed by the lifecycle CLI."""

    SUCCESS = 0
    RUNTIME_ERROR = 1
    USAGE_ERROR = 2


class LifecycleError(Exception):
    """An expected, user-facing lifecycle command failure."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
