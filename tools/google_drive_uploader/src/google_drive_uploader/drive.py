import mimetypes
from pathlib import Path
from typing import NotRequired, TypedDict, cast

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import Resource, build
from googleapiclient.http import MediaFileUpload

from .auth import DriveConfigurationError

BLOCKED_UPLOAD_SUFFIXES = (".pem", ".key", ".p12", ".pfx")
BLOCKED_UPLOAD_NAMES = frozenset(
    {"credentials.json", "token.json", "client_secret.json", "service-account.json"}
)
BLOCKED_UPLOAD_NAME_PARTS = ("credential", "secret", "token", "private-key", "private_key")


class DriveUser(TypedDict):
    emailAddress: NotRequired[str]


class DriveAbout(TypedDict):
    user: NotRequired[DriveUser]


class DriveFile(TypedDict):
    id: str
    name: str
    size: str
    webViewLink: NotRequired[str]
    parents: NotRequired[list[str]]


class UploadResponse(TypedDict):
    id: str


def build_drive_service(credentials: Credentials) -> Resource:
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def account_email(service: Resource) -> str:
    about = cast(
        DriveAbout,
        service.about()
        .get(fields="user(displayName,emailAddress),storageQuota(limit,usage)")
        .execute(),
    )
    return about.get("user", {}).get("emailAddress", "unknown")


def validate_upload_paths(paths: list[Path]) -> None:
    for path in paths:
        normalized_name = path.name.casefold()
        if (
            normalized_name in BLOCKED_UPLOAD_NAMES
            or normalized_name.endswith(BLOCKED_UPLOAD_SUFFIXES)
            or any(part in normalized_name for part in BLOCKED_UPLOAD_NAME_PARTS)
        ):
            raise DriveConfigurationError(f"アップロード禁止のファイル種別です: {path.name}")


def upload_files(service: Resource, paths: list[Path], folder_id: str | None) -> list[DriveFile]:
    validate_upload_paths(paths)
    uploaded: list[DriveFile] = []
    for path in paths:
        if not path.is_file():
            raise DriveConfigurationError(f"ファイルがありません: {path}")
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        metadata: dict[str, str | list[str]] = {"name": path.name}
        if folder_id:
            metadata["parents"] = [folder_id]
        media = MediaFileUpload(str(path), mimetype=media_type, resumable=True)
        request = service.files().create(
            body=metadata,
            media_body=media,
            fields="id,name,size,webViewLink,parents",
        )
        response = None
        while response is None:
            _, response = request.next_chunk()
        response = cast(UploadResponse, response)
        file_id = response["id"]
        verified = cast(
            DriveFile,
            service.files()
            .get(fileId=file_id, fields="id,name,size,webViewLink,parents")
            .execute(),
        )
        expected_size = path.stat().st_size
        if int(verified.get("size", -1)) != expected_size or verified.get("name") != path.name:
            raise DriveConfigurationError(f"アップロード検証に失敗しました: {path.name}")
        uploaded.append(verified)
    return uploaded
