"""Typed Herdr workspace operations."""

from collections.abc import Mapping
from pathlib import Path
from typing import cast

from .errors import HerdrError
from .models import CreatedResources, WorkspaceInfo
from .transport import HerdrTransport


class WorkspaceClient:
    def __init__(self, transport: HerdrTransport) -> None:
        self._transport = transport

    def get(self, workspace_id: str) -> WorkspaceInfo:
        item = self._transport.member(
            self._transport.request(["workspace", "get", workspace_id]), "workspace"
        )
        actual_id = self._transport.string(item, "workspace_id")
        if actual_id != workspace_id:
            raise HerdrError("Herdr workspace identity mismatch")
        return WorkspaceInfo(actual_id, self._transport.string(item, "label"))

    def list(self) -> list[WorkspaceInfo]:
        raw_items = self._transport.request(["workspace", "list"]).get("workspaces")
        if not isinstance(raw_items, list):
            raise HerdrError("Herdr response has no workspaces list")
        items: list[WorkspaceInfo] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                raise HerdrError("Herdr workspace response contains an invalid workspace")
            item = cast(Mapping[str, object], raw_item)
            items.append(
                WorkspaceInfo(
                    self._transport.string(item, "workspace_id"),
                    self._transport.string(item, "label"),
                )
            )
        return items

    def find(self, workspace_id: str) -> WorkspaceInfo | None:
        return next((item for item in self.list() if item.workspace_id == workspace_id), None)

    def create(self, label: str, cwd: Path) -> CreatedResources:
        payload = self._transport.request(
            ["workspace", "create", "--label", label, "--cwd", str(cwd), "--no-focus"]
        )
        workspace = self._transport.member(payload, "workspace")
        tab = self._transport.member(payload, "tab")
        pane = self._transport.member(payload, "root_pane")
        workspace_id = self._transport.string(workspace, "workspace_id")
        tab_id = self._transport.string(tab, "tab_id")
        pane_id = self._transport.string(pane, "pane_id")
        if (
            self._transport.string(tab, "workspace_id") != workspace_id
            or self._transport.string(pane, "tab_id") != tab_id
        ):
            raise HerdrError("Herdr create response has inconsistent resource identities")
        return CreatedResources(workspace_id, tab_id, pane_id)

    def close(self, workspace_id: str) -> None:
        self._transport.request(["workspace", "close", workspace_id])
