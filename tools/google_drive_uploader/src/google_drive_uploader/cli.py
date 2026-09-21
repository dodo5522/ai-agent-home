import argparse
from pathlib import Path

from googleapiclient.errors import HttpError

from .auth import DriveConfig, DriveConfigurationError, load_credentials
from .drive import account_email, build_drive_service, create_folder, upload_files


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Google Drive OAuth and upload tool")
    subparsers = parser.add_subparsers(dest="command", required=True)
    auth = subparsers.add_parser("auth", help="初回OAuth認証またはトークン更新")
    auth.add_argument("--port", type=int, default=8080, help="localhost callback port")
    subparsers.add_parser("status", help="認証済みアカウントを表示")
    upload = subparsers.add_parser("upload", help="ファイルをDriveへアップロード")
    upload.add_argument("paths", nargs="+", type=Path)
    upload.add_argument("--folder-id")
    upload.add_argument("--folder-name", help="新規作成する成果物フォルダ名")
    upload.add_argument("--parent-folder-id", help="新規成果物フォルダの親フォルダID")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = DriveConfig.from_environment()
    try:
        if args.command == "auth":
            credentials = load_credentials(config, interactive=True, auth_port=args.port)
            print(f"OAuth認証済み（スコープ数: {len(credentials.scopes or ())}）")
        else:
            credentials = load_credentials(config, interactive=False)
            service = build_drive_service(credentials)
            if args.command == "status":
                print(f"認証済み: {account_email(service)}")
            else:
                if args.folder_id and args.folder_name:
                    raise DriveConfigurationError(
                        "--folder-idと--folder-nameは同時に指定できません"
                    )
                folder_id = args.folder_id
                if args.folder_name:
                    folder = create_folder(service, args.folder_name, args.parent_folder_id)
                    folder_id = folder["id"]
                    print(
                        f"フォルダ: {folder['name']} {folder['id']} {folder.get('webViewLink', '')}"
                    )
                elif args.parent_folder_id:
                    raise DriveConfigurationError("--parent-folder-idには--folder-nameが必要です")
                for uploaded in upload_files(service, args.paths, folder_id):
                    print(f"{uploaded['name']}: {uploaded['id']} {uploaded.get('webViewLink', '')}")
    except (DriveConfigurationError, HttpError) as error:
        print(f"エラー: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
