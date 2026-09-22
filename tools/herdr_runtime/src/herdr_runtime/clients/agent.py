"""Typed Herdr Agent operations."""

from pathlib import Path

from .._decoding import JsonObject, required_object, required_string
from ..errors import HerdrError
from ..models import AgentInfo
from ..transport import HerdrTransport


class AgentClient:
    def __init__(self, transport: HerdrTransport) -> None:
        self._transport = transport

    @staticmethod
    def _info(agent: JsonObject) -> AgentInfo:
        session = agent.get("agent_session")
        kind = "codex"
        if isinstance(session, dict) and isinstance(session.get("agent"), str):
            kind = required_string(session, "agent")
        return AgentInfo(
            name=required_string(agent, "agent"),
            kind=kind,
            pane_id=required_string(agent, "pane_id"),
            workspace_id=required_string(agent, "workspace_id"),
            cwd=Path(required_string(agent, "cwd")),
        )

    def list(self) -> list[AgentInfo]:
        raw_items = self._transport.request(["agent", "list"]).get("agents")
        if not isinstance(raw_items, list):
            raise HerdrError("Herdr response has no agents list")
        items: list[AgentInfo] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                raise HerdrError("Herdr Agent response contains an invalid Agent")
            items.append(self._info(raw_item))
        return items

    def find(self, name: str) -> AgentInfo | None:
        return next((agent for agent in self.list() if agent.name == name), None)

    def start(self, name: str, pane_id: str, kind: str = "codex") -> AgentInfo:
        payload = self._transport.request(
            ["agent", "start", name, "--kind", kind, "--pane", pane_id]
        )
        agent = self._info(required_object(payload, "agent"))
        if agent.name != name or agent.pane_id != pane_id or agent.kind != kind:
            raise HerdrError("Herdr Agent start response has inconsistent identity")
        return agent

    def prompt(self, name: str, text: str) -> None:
        self._transport.request(["agent", "prompt", name, text])
