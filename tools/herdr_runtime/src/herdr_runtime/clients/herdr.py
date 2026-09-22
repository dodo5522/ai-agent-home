"""Composition root for typed Herdr resource clients."""

from ..runner import CommandRunner
from ..transport import HerdrTransport
from .agent import AgentClient
from .pane import PaneClient
from .tab import TabClient
from .workspace import WorkspaceClient


class HerdrClient:
    """Expose focused resource clients over one shared Herdr transport."""

    def __init__(self, runner: CommandRunner, herdr_bin: str = "herdr") -> None:
        transport = HerdrTransport(runner, herdr_bin)
        self.workspace = WorkspaceClient(transport)
        self.tab = TabClient(transport)
        self.pane = PaneClient(transport)
        self.agent = AgentClient(transport)
