"""Typed Herdr pane operations."""

from pathlib import Path

from .._decoding import JsonObject, optional_string, required_object, required_string
from ..errors import HerdrError
from ..models import PaneInfo
from ..transport import HerdrTransport


class PaneClient:
    def __init__(self, transport: HerdrTransport) -> None:
        self._transport = transport

    @staticmethod
    def _info(pane: JsonObject) -> PaneInfo:
        cwd = optional_string(pane, "cwd")
        return PaneInfo(
            required_string(pane, "pane_id"),
            required_string(pane, "tab_id"),
            optional_string(pane, "workspace_id"),
            None if cwd is None else Path(cwd),
            optional_string(pane, "agent"),
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
            pane = self._info(raw_item)
            if pane.workspace_id is not None and pane.workspace_id != workspace_id:
                raise HerdrError("Herdr pane workspace identity mismatch")
            items.append(pane)
        return items

    def for_tab(self, workspace_id: str, tab_id: str) -> list[PaneInfo]:
        return [pane for pane in self.list(workspace_id) if pane.tab_id == tab_id]

    def get(self, pane_id: str) -> PaneInfo:
        pane = required_object(self._transport.request(["pane", "get", pane_id]), "pane")
        if required_string(pane, "pane_id") != pane_id:
            raise HerdrError("Herdr pane identity mismatch")
        return self._info(pane)
