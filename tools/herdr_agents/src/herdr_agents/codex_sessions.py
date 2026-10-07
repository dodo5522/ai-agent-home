"""Read-only validation of locally stored Codex sessions."""

import json
import sqlite3
from pathlib import Path


class CodexSessionFiles:
    """Determine whether one exact Codex session has usable local files."""

    def __init__(self, index_path: Path) -> None:
        self._index_path = index_path

    def is_usable(self, session_id: str) -> bool:
        """Return whether one exact local Codex session has a valid rollout."""
        if not session_id:
            return False
        if self._is_regular_file(self._index_path.parent / "state_5.sqlite"):
            return self._current_session_is_usable(session_id)
        if self._is_regular_file(self._index_path):
            return self._legacy_session_is_usable(session_id)
        return False

    def _legacy_session_is_usable(self, session_id: str) -> bool:
        try:
            indexed = any(
                isinstance(item, dict) and item.get("id") == session_id
                for item in self._json_lines(self._index_path)
            )
        except (OSError, UnicodeError, json.JSONDecodeError):
            return False
        if not indexed:
            return False
        sessions = self._index_path.parent / "sessions"
        try:
            candidates = [
                path
                for path in sessions.rglob(f"*-{session_id}.jsonl")
                if self._is_regular_file(path)
            ]
        except OSError:
            return False
        if len(candidates) != 1:
            return False
        try:
            return any(isinstance(item, dict) for item in self._json_lines(candidates[0]))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return False

    def _current_session_is_usable(self, session_id: str) -> bool:
        database_path = self._index_path.parent / "state_5.sqlite"
        if not self._is_regular_file(database_path):
            return False
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
            rows = connection.execute(
                "SELECT rollout_path FROM threads WHERE id = ?", (session_id,)
            ).fetchall()
        except sqlite3.Error:
            return False
        finally:
            if connection is not None:
                connection.close()
        if len(rows) != 1 or not isinstance(rows[0][0], str):
            return False
        rollout = Path(rows[0][0])
        sessions = self._index_path.parent / "sessions"
        try:
            rollout.relative_to(sessions)
        except ValueError:
            return False
        if not self._is_regular_file(rollout):
            return False
        try:
            return any(isinstance(item, dict) for item in self._json_lines(rollout))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return False

    @staticmethod
    def _is_regular_file(path: Path) -> bool:
        return path.is_file() and not path.is_symlink()

    @staticmethod
    def _json_lines(path: Path) -> list[object]:
        with path.open(encoding="utf-8") as stream:
            return [json.loads(line) for line in stream if line.strip()]
