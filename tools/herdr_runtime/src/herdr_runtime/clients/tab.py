"""Typed Herdr tab operations."""

from pathlib import Path

from .._decoding import required_object, required_string
from ..errors import HerdrError
from ..models import CreatedResources, TabInfo
from ..transport import HerdrTransport


class TabClient:
    def __init__(self, transport: HerdrTransport) -> None:
        self._transport = transport

    def get(self, tab_id: str) -> TabInfo:
        item = required_object(self._transport.request(["tab", "get", tab_id]), "tab")
        actual_id = required_string(item, "tab_id")
        if actual_id != tab_id:
            raise HerdrError("Herdr tab identity mismatch")
        return TabInfo(
            actual_id,
            required_string(item, "workspace_id"),
            required_string(item, "label"),
        )

    def list(self) -> list[TabInfo]:
        raw_items = self._transport.request(["tab", "list"]).get("tabs")
        if not isinstance(raw_items, list):
            raise HerdrError("Herdr response has no tabs list")
        items: list[TabInfo] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                raise HerdrError("Herdr tab response contains an invalid tab")
            items.append(
                TabInfo(
                    required_string(raw_item, "tab_id"),
                    required_string(raw_item, "workspace_id"),
                    required_string(raw_item, "label"),
                )
            )
        return items

    def find(self, tab_id: str) -> TabInfo | None:
        return next((item for item in self.list() if item.tab_id == tab_id), None)

    def create(self, workspace_id: str, label: str, cwd: Path) -> CreatedResources:
        payload = self._transport.request(
            [
                "tab",
                "create",
                "--workspace",
                workspace_id,
                "--cwd",
                str(cwd),
                "--label",
                label,
                "--no-focus",
            ]
        )
        tab = required_object(payload, "tab")
        pane = required_object(payload, "root_pane")
        tab_id = required_string(tab, "tab_id")
        pane_id = required_string(pane, "pane_id")
        if (
            required_string(tab, "workspace_id") != workspace_id
            or required_string(pane, "tab_id") != tab_id
        ):
            raise HerdrError("Herdr create response has inconsistent resource identities")
        return CreatedResources(workspace_id, tab_id, pane_id)

    def rename(self, tab_id: str, label: str) -> TabInfo:
        item = required_object(self._transport.request(["tab", "rename", tab_id, label]), "tab")
        actual_id = required_string(item, "tab_id")
        if actual_id != tab_id or required_string(item, "label") != label:
            raise HerdrError("Herdr tab rename response has inconsistent identity")
        return TabInfo(actual_id, required_string(item, "workspace_id"), label)

    def close(self, tab_id: str) -> None:
        self._transport.request(["tab", "close", tab_id])
