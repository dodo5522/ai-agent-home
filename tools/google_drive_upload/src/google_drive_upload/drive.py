from __future__ import annotations

import json
import os
import secrets
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ("https://www.googleapis.com/auth/drive",)
DEFAULT_CONFIG_DIR = Path.home() / ".config" / "google-drive"


class DriveConfigurationError(RuntimeError):
    """Raised when local OAuth configuration is missing or unsafe."""


@dataclass(frozen=True)
class DriveConfig:
    config_dir: Path
    credentials_path: Path
    token_path: Path

    @classmethod
    def from_environment(cls) -> DriveConfig:
        configured = os.environ.get("GOOGLE_DRIVE_CONFIG_DIR")
        directory = Path(configured).expanduser() if configured else DEFAULT_CONFIG_DIR
        return cls(directory, directory / "credentials.json", directory / "token.json")

    def validate(self) -> None:
        if not self.config_dir.is_dir():
            raise DriveConfigurationError(f"設定ディレクトリがありません: {self.config_dir}")
        if self.config_dir.stat().st_mode & 0o077:
            raise DriveConfigurationError(
                f"設定ディレクトリの権限を700にしてください: {self.config_dir}"
            )
        if not self.credentials_path.is_file():
            raise DriveConfigurationError(f"credentials.jsonがありません: {self.credentials_path}")
        if self.credentials_path.stat().st_mode & 0o077:
            raise DriveConfigurationError("credentials.jsonの権限を600以下にしてください")


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    with tempfile.NamedTemporaryFile(
        "w", dir=path.parent, delete=False, encoding="utf-8"
    ) as handle:
        temporary = Path(handle.name)
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def load_credentials(
    config: DriveConfig, *, interactive: bool, auth_port: int = 8080
) -> Credentials:
    config.validate()
    credentials: Credentials | None = None
    if config.token_path.is_file():
        if config.token_path.stat().st_mode & 0o077:
            raise DriveConfigurationError("token.jsonの権限を600以下にしてください")
        try:
            credentials = Credentials.from_authorized_user_file(str(config.token_path), SCOPES)
        except (ValueError, OSError) as error:
            raise DriveConfigurationError("token.jsonを読み込めません") from error
    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        _write_private_json(config.token_path, json.loads(credentials.to_json()))
    if credentials and credentials.valid:
        return credentials
    if not interactive:
        raise DriveConfigurationError("認証が必要です。authコマンドを実行してください")
    flow = InstalledAppFlow.from_client_secrets_file(str(config.credentials_path), SCOPES)
    state = secrets.token_urlsafe(16)
    credentials = flow.run_local_server(
        host="127.0.0.1",
        port=auth_port,
        open_browser=False,
        authorization_prompt_message=("ブラウザーで次のURLを開いて認証してください:\n{url}\n"),
        state=state,
    )
    _write_private_json(config.token_path, json.loads(credentials.to_json()))
    return credentials
