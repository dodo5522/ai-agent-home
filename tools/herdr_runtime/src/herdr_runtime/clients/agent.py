"""Typed Herdr Agent operations."""

from collections.abc import Sequence
from pathlib import Path

from .._decoding import JsonObject, optional_string, required_object, required_string
from ..errors import HerdrError
from ..models import AgentInfo
from ..transport import HerdrTransport


class AgentClient:
    def __init__(self, transport: HerdrTransport) -> None:
        self._transport = transport

    @staticmethod
    def _info(agent: JsonObject) -> AgentInfo:
        session_id: str | None = None
        raw_session = agent.get("agent_session")
        if raw_session is not None:
            if not isinstance(raw_session, dict):
                raise HerdrError("Herdr Agent session is invalid")
            if (
                required_string(raw_session, "agent") != "codex"
                or required_string(raw_session, "kind") != "id"
            ):
                raise HerdrError("Herdr Agent session is invalid")
            session_id = required_string(raw_session, "value")
        return AgentInfo(
            name=required_string(agent, "name"),
            kind=required_string(agent, "agent"),
            pane_id=required_string(agent, "pane_id"),
            workspace_id=required_string(agent, "workspace_id"),
            cwd=Path(required_string(agent, "cwd")),
            codex_session_id=session_id,
        )

    def list(self) -> list[AgentInfo]:
        raw_items = self._transport.request(["agent", "list"]).get("agents")
        if not isinstance(raw_items, list):
            raise HerdrError("Herdr response has no agents list")
        items: list[AgentInfo] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                raise HerdrError("Herdr Agent response contains an invalid Agent")
            if optional_string(raw_item, "name") is None:
                continue
            items.append(self._info(raw_item))
        return items

    def find(self, name: str) -> AgentInfo | None:
        return next((agent for agent in self.list() if agent.name == name), None)

    def start(
        self, name: str, pane_id: str, kind: str = "codex", native_args: Sequence[str] = ()
    ) -> AgentInfo:
        arguments = ["agent", "start", name, "--kind", kind, "--pane", pane_id]
        if native_args:
            arguments.extend(("--", *native_args))
        payload = self._transport.request(
            arguments
        )
        agent = self._info(required_object(payload, "agent"))
        if agent.name != name or agent.pane_id != pane_id or agent.kind != kind:
            raise HerdrError("Herdr Agent start response has inconsistent identity")
        return agent

    def prompt(self, name: str, text: str) -> None:
        self._transport.request(["agent", "prompt", name, text])
