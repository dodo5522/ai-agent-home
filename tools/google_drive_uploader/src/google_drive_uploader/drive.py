import mimetypes
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from .auth import DriveConfigurationError


def build_drive_service(credentials: object) -> object:
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def account_email(service: object) -> str:
    about = (
        service.about()
        .get(fields="user(displayName,emailAddress),storageQuota(limit,usage)")
        .execute()
    )
    return about.get("user", {}).get("emailAddress", "unknown")


def upload_files(
    service: object, paths: list[Path], folder_id: str | None
) -> list[dict[str, object]]:
    uploaded: list[dict[str, object]] = []
    for path in paths:
        if not path.is_file():
            raise DriveConfigurationError(f"ファイルがありません: {path}")
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        metadata: dict[str, object] = {"name": path.name}
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
        file_id = response["id"]
        verified = (
            service.files().get(fileId=file_id, fields="id,name,size,webViewLink,parents").execute()
        )
        expected_size = path.stat().st_size
        if int(verified.get("size", -1)) != expected_size or verified.get("name") != path.name:
            raise DriveConfigurationError(f"アップロード検証に失敗しました: {path.name}")
        uploaded.append(verified)
    return uploaded
