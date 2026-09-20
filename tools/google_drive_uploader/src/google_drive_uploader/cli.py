import argparse
import mimetypes
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from .drive import DriveConfig, DriveConfigurationError, load_credentials


def _service(config: DriveConfig, *, interactive: bool) -> object:
    credentials = load_credentials(config, interactive=interactive)
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def _status(config: DriveConfig) -> None:
    credentials = load_credentials(config, interactive=False)
    service = build("drive", "v3", credentials=credentials, cache_discovery=False)
    about = (
        service.about()
        .get(fields="user(displayName,emailAddress),storageQuota(limit,usage)")
        .execute()
    )
    user = about.get("user", {})
    print(f"認証済み: {user.get('emailAddress', 'unknown')}")


def _upload(config: DriveConfig, paths: list[Path], folder_id: str | None) -> None:
    service = _service(config, interactive=False)
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
        print(f"{verified['name']}: {verified['id']} {verified.get('webViewLink', '')}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Google Drive OAuth and upload tool")
    subparsers = parser.add_subparsers(dest="command", required=True)
    auth = subparsers.add_parser("auth", help="初回OAuth認証またはトークン更新")
    auth.add_argument("--port", type=int, default=8080, help="localhost callback port")
    subparsers.add_parser("status", help="認証済みアカウントを表示")
    upload = subparsers.add_parser("upload", help="ファイルをDriveへアップロード")
    upload.add_argument("paths", nargs="+", type=Path)
    upload.add_argument("--folder-id")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = DriveConfig.from_environment()
    try:
        if args.command == "auth":
            credentials = load_credentials(config, interactive=True, auth_port=args.port)
            print(f"OAuth認証済み（スコープ数: {len(credentials.scopes or ())}）")
        elif args.command == "status":
            _status(config)
        else:
            _upload(config, args.paths, args.folder_id)
    except (DriveConfigurationError, HttpError) as error:
        print(f"エラー: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
