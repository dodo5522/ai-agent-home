import json
import os
from pathlib import Path

import pytest

from google_drive_uploader.auth import DriveConfig, DriveConfigurationError, _write_private_json
from google_drive_uploader.drive import validate_upload_paths


def test_config_requires_private_directory(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    os.chmod(config_dir, 0o755)
    credentials = config_dir / "credentials.json"
    credentials.write_text(json.dumps({"installed": {}}))
    os.chmod(credentials, 0o600)
    with pytest.raises(DriveConfigurationError, match="権限"):
        DriveConfig(config_dir, credentials, config_dir / "token.json").validate()


def test_private_json_write_is_atomic_and_private(tmp_path: Path) -> None:
    path = tmp_path / "token.json"
    _write_private_json(path, {"token": "redacted-test-value"})
    assert json.loads(path.read_text())["token"] == "redacted-test-value"
    assert path.stat().st_mode & 0o077 == 0


@pytest.mark.parametrize("filename", ["credentials.json", "token.json", "private-key.pem"])
def test_upload_rejects_sensitive_files(tmp_path: Path, filename: str) -> None:
    with pytest.raises(DriveConfigurationError, match="アップロード禁止"):
        validate_upload_paths([tmp_path / filename])


def test_upload_allows_non_sensitive_files(tmp_path: Path) -> None:
    validate_upload_paths([tmp_path / "rabbit.stl"])
