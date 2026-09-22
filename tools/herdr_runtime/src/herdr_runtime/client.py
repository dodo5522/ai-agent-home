"""Composition root for typed Herdr resource clients."""

from .agents import AgentClient
from .panes import PaneClient
from .runner import CommandRunner
from .tabs import TabClient
from .transport import HerdrTransport
from .workspaces import WorkspaceClient


class HerdrClient:
    """Expose focused resource clients over one shared Herdr transport."""

    def __init__(self, runner: CommandRunner, herdr_bin: str = "herdr") -> None:
        transport = HerdrTransport(runner, herdr_bin)
        self.workspace = WorkspaceClient(transport)
        self.tab = TabClient(transport)
        self.pane = PaneClient(transport)
        self.agent = AgentClient(transport)
