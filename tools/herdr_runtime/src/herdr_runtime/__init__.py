"""Shared typed boundaries for Herdr automation tools."""

from .agents import AgentClient
from .client import HerdrClient
from .errors import HerdrError, HerdrRuntimeError, RuntimeCommandError
from .models import AgentInfo, CreatedResources, PaneInfo, TabInfo, WorkspaceInfo
from .panes import PaneClient
from .runner import CommandResult, CommandRunner, SubprocessRunner
from .tabs import TabClient
from .workspaces import WorkspaceClient

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
