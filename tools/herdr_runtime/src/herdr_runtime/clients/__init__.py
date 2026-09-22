"""Focused clients for Herdr resources."""

from .agent import AgentClient
from .herdr import HerdrClient
from .pane import PaneClient
from .tab import TabClient
from .workspace import WorkspaceClient

__all__ = ["AgentClient", "HerdrClient", "PaneClient", "TabClient", "WorkspaceClient"]
