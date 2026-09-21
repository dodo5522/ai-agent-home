"""Shared typed boundaries for Herdr automation tools."""

from .client import (
    AgentInfo,
    CreatedResources,
    HerdrClient,
    PaneInfo,
    TabInfo,
    WorkspaceInfo,
)
from .errors import HerdrError, HerdrRuntimeError, RuntimeCommandError
from .runner import CommandResult, CommandRunner, SubprocessRunner

__all__ = [
    "AgentInfo",
    "CommandResult",
    "CommandRunner",
    "CreatedResources",
    "HerdrClient",
    "HerdrError",
    "HerdrRuntimeError",
    "PaneInfo",
    "RuntimeCommandError",
    "SubprocessRunner",
    "TabInfo",
    "WorkspaceInfo",
]
