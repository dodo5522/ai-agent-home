"""Read-only validation of locally stored Codex sessions."""

import json
from pathlib import Path


class CodexSessionFiles:
    """Determine whether one exact Codex session has usable local files."""

    def __init__(self, index_path: Path) -> None:
        self._index_path = index_path

    def is_usable(self, session_id: str) -> bool:
        """Return whether an indexed session has one valid rollout file."""
        if not session_id or not self._is_regular_file(self._index_path):
            return False
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

    @staticmethod
    def _is_regular_file(path: Path) -> bool:
        return path.is_file() and not path.is_symlink()

    @staticmethod
    def _json_lines(path: Path) -> list[object]:
        with path.open(encoding="utf-8") as stream:
            return [json.loads(line) for line in stream if line.strip()]
