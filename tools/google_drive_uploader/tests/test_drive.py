from typing import Any

import pytest

from google_drive_uploader.auth import DriveConfigurationError
from google_drive_uploader.drive import create_folder


class FakeRequest:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response

    def execute(self) -> dict[str, Any]:
        return self.response


class FakeFiles:
    def __init__(self) -> None:
        self.body: dict[str, Any] | None = None
        self.fields: str | None = None

    def create(self, *, body: dict[str, Any], fields: str) -> FakeRequest:
        self.body = body
        self.fields = fields
        return FakeRequest(
            {
                "id": "folder-123",
                "name": body["name"],
                "mimeType": body["mimeType"],
                "webViewLink": "https://drive.google.test/folder-123",
            }
        )


class FakeService:
    def __init__(self) -> None:
        self.files_api = FakeFiles()

    def files(self) -> FakeFiles:
        return self.files_api


def test_create_folder_creates_drive_folder_under_parent() -> None:
    service = FakeService()

    folder = create_folder(service, "chair-final", parent_id="artifacts-root")

    assert folder["id"] == "folder-123"
    assert folder["name"] == "chair-final"
    assert service.files_api.body == {
        "name": "chair-final",
        "mimeType": "application/vnd.google-apps.folder",
        "parents": ["artifacts-root"],
    }
    assert service.files_api.fields == "id,name,mimeType,webViewLink,parents"


def test_create_folder_rejects_blank_name() -> None:
    with pytest.raises(DriveConfigurationError, match="フォルダ名"):
        create_folder(FakeService(), "  ")
