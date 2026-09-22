"""Typed Herdr Agent operations."""

from collections.abc import Mapping
from pathlib import Path
from typing import cast

from .errors import HerdrError
from .models import AgentInfo
from .transport import HerdrTransport


class AgentClient:
    def __init__(self, transport: HerdrTransport) -> None:
        self._transport = transport

    def _info(self, agent: Mapping[str, object]) -> AgentInfo:
        session = agent.get("agent_session")
        kind = "codex"
        if isinstance(session, dict) and isinstance(session.get("agent"), str):
            kind = self._transport.string(cast(Mapping[str, object], session), "agent")
        return AgentInfo(
            name=self._transport.string(agent, "agent"),
            kind=kind,
            pane_id=self._transport.string(agent, "pane_id"),
            workspace_id=self._transport.string(agent, "workspace_id"),
            cwd=Path(self._transport.string(agent, "cwd")),
        )

    def list(self) -> list[AgentInfo]:
        raw_items = self._transport.request(["agent", "list"]).get("agents")
        if not isinstance(raw_items, list):
            raise HerdrError("Herdr response has no agents list")
        items: list[AgentInfo] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                raise HerdrError("Herdr Agent response contains an invalid Agent")
            items.append(self._info(cast(Mapping[str, object], raw_item)))
        return items

    def find(self, name: str) -> AgentInfo | None:
        return next((agent for agent in self.list() if agent.name == name), None)

    def start(self, name: str, pane_id: str, kind: str = "codex") -> AgentInfo:
        payload = self._transport.request(
            ["agent", "start", name, "--kind", kind, "--pane", pane_id]
        )
        agent = self._info(self._transport.member(payload, "agent"))
        if agent.name != name or agent.pane_id != pane_id or agent.kind != kind:
            raise HerdrError("Herdr Agent start response has inconsistent identity")
        return agent

    def prompt(self, name: str, text: str) -> None:
        self._transport.request(["agent", "prompt", name, text])
