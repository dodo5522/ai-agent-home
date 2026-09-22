"""Shared typed boundaries for Herdr automation tools."""

from .clients import AgentClient, HerdrClient, PaneClient, TabClient, WorkspaceClient
from .errors import HerdrError, HerdrRuntimeError, RuntimeCommandError
from .models import AgentInfo, CreatedResources, PaneInfo, TabInfo, WorkspaceInfo
from .runner import CommandResult, CommandRunner, SubprocessRunner

__all__ = [
    "AgentInfo",
    "AgentClient",
    "CommandResult",
    "CommandRunner",
    "CreatedResources",
    "HerdrClient",
    "HerdrError",
    "HerdrRuntimeError",
    "PaneInfo",
    "PaneClient",
    "RuntimeCommandError",
    "SubprocessRunner",
    "TabInfo",
    "TabClient",
    "WorkspaceInfo",
    "WorkspaceClient",
]
