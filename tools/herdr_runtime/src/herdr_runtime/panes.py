"""Typed Herdr pane operations."""

from collections.abc import Mapping
from pathlib import Path
from typing import cast

from .errors import HerdrError
from .models import PaneInfo
from .transport import HerdrTransport


class PaneClient:
    def __init__(self, transport: HerdrTransport) -> None:
        self._transport = transport

    def _info(self, pane: Mapping[str, object]) -> PaneInfo:
        cwd_value = pane.get("cwd")
        cwd = None
        if cwd_value is not None:
            cwd = Path(
                self._transport.string(cast(Mapping[str, object], {"cwd": cwd_value}), "cwd")
            )
        workspace_value = pane.get("workspace_id")
        agent_value = pane.get("agent")
        return PaneInfo(
            self._transport.string(pane, "pane_id"),
            self._transport.string(pane, "tab_id"),
            workspace_value if isinstance(workspace_value, str) else None,
            cwd,
            agent_value if isinstance(agent_value, str) else None,
        )

    def list(self, workspace_id: str) -> list[PaneInfo]:
        raw_items = self._transport.request(["pane", "list", "--workspace", workspace_id]).get(
            "panes"
        )
        if not isinstance(raw_items, list):
            raise HerdrError("Herdr response has no panes list")
        items: list[PaneInfo] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                raise HerdrError("Herdr pane response contains an invalid pane")
            pane = self._info(cast(Mapping[str, object], raw_item))
            if pane.workspace_id is not None and pane.workspace_id != workspace_id:
                raise HerdrError("Herdr pane workspace identity mismatch")
            items.append(pane)
        return items

    def for_tab(self, workspace_id: str, tab_id: str) -> list[PaneInfo]:
        return [pane for pane in self.list(workspace_id) if pane.tab_id == tab_id]

    def get(self, pane_id: str) -> PaneInfo:
        pane = self._transport.member(self._transport.request(["pane", "get", pane_id]), "pane")
        if self._transport.string(pane, "pane_id") != pane_id:
            raise HerdrError("Herdr pane identity mismatch")
        return self._info(pane)
