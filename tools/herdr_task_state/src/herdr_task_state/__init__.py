"""Herdr task-state Pydantic models and parsing helpers."""

from .model import (
    AgentReference,
    CleanupAction,
    CleanupProgress,
    HerdrReference,
    Model,
    PersistentAgentReference,
    StateValidationError,
    Task,
    TaskKey,
    TaskState,
    Workstream,
    migrate_state,
)
from .sessions import AgentBinding, SessionMapping

__all__ = [
    "AgentReference",
    "AgentBinding",
    "CleanupAction",
    "CleanupProgress",
    "HerdrReference",
    "Model",
    "PersistentAgentReference",
    "StateValidationError",
    "SessionMapping",
    "Task",
    "TaskKey",
    "TaskState",
    "Workstream",
    "migrate_state",
]
