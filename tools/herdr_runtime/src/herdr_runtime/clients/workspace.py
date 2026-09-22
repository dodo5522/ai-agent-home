"""Typed Herdr workspace operations."""

from pathlib import Path

from .._decoding import required_object, required_string
from ..errors import HerdrError
from ..models import CreatedResources, WorkspaceInfo
from ..transport import HerdrTransport


class WorkspaceClient:
    def __init__(self, transport: HerdrTransport) -> None:
        self._transport = transport

    def get(self, workspace_id: str) -> WorkspaceInfo:
        item = required_object(
            self._transport.request(["workspace", "get", workspace_id]), "workspace"
        )
        actual_id = required_string(item, "workspace_id")
        if actual_id != workspace_id:
            raise HerdrError("Herdr workspace identity mismatch")
        return WorkspaceInfo(actual_id, required_string(item, "label"))

    def list(self) -> list[WorkspaceInfo]:
        raw_items = self._transport.request(["workspace", "list"]).get("workspaces")
        if not isinstance(raw_items, list):
            raise HerdrError("Herdr response has no workspaces list")
        items: list[WorkspaceInfo] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                raise HerdrError("Herdr workspace response contains an invalid workspace")
            items.append(
                WorkspaceInfo(
                    required_string(raw_item, "workspace_id"),
                    required_string(raw_item, "label"),
                )
            )
        return items

    def find(self, workspace_id: str) -> WorkspaceInfo | None:
        return next((item for item in self.list() if item.workspace_id == workspace_id), None)

    def create(self, label: str, cwd: Path) -> CreatedResources:
        payload = self._transport.request(
            ["workspace", "create", "--label", label, "--cwd", str(cwd), "--no-focus"]
        )
        workspace = required_object(payload, "workspace")
        tab = required_object(payload, "tab")
        pane = required_object(payload, "root_pane")
        workspace_id = required_string(workspace, "workspace_id")
        tab_id = required_string(tab, "tab_id")
        pane_id = required_string(pane, "pane_id")
        if (
            required_string(tab, "workspace_id") != workspace_id
            or required_string(pane, "tab_id") != tab_id
        ):
            raise HerdrError("Herdr create response has inconsistent resource identities")
        return CreatedResources(workspace_id, tab_id, pane_id)

    def close(self, workspace_id: str) -> None:
        self._transport.request(["workspace", "close", workspace_id])
