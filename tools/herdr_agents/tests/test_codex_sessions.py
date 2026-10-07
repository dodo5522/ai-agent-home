import json
import sqlite3
from pathlib import Path

from herdr_agents.codex_sessions import CodexSessionFiles


def write_index(tmp_path: Path, session_id: str, content: str | None = None) -> Path:
    index = tmp_path / "session_index.jsonl"
    index.write_text(content or json.dumps({"id": session_id}) + "\n", encoding="utf-8")
    return index


def test_indexed_session_without_rollout_is_not_usable(tmp_path: Path) -> None:
    inspector = CodexSessionFiles(index_path=write_index(tmp_path, "session-a"))

    assert inspector.is_usable("session-a") is False


def test_malformed_index_or_rollout_is_not_usable(tmp_path: Path) -> None:
    index = write_index(tmp_path, "session-a", "not json\n")

    assert CodexSessionFiles(index_path=index).is_usable("session-a") is False


def test_rollout_requires_a_json_object(tmp_path: Path) -> None:
    index = write_index(tmp_path, "session-a")
    rollout = tmp_path / "sessions" / "2026" / "rollout-session-a.jsonl"
    rollout.parent.mkdir(parents=True)
    rollout.write_text('"scalar"\n', encoding="utf-8")

    assert CodexSessionFiles(index_path=index).is_usable("session-a") is False


def test_current_codex_thread_with_a_valid_rollout_is_usable(tmp_path: Path) -> None:
    session_id = "session-a"
    write_index(tmp_path, "a-stale-session")
    rollout = tmp_path / "sessions" / "2026" / "rollout-session-a.jsonl"
    rollout.parent.mkdir(parents=True)
    rollout.write_text(json.dumps({"type": "session_meta"}) + "\n", encoding="utf-8")
    database = sqlite3.connect(tmp_path / "state_5.sqlite")
    try:
        database.execute("CREATE TABLE threads (id TEXT, rollout_path TEXT)")
        database.execute(
            "INSERT INTO threads (id, rollout_path) VALUES (?, ?)",
            (session_id, str(rollout)),
        )
        database.commit()
    finally:
        database.close()

    assert CodexSessionFiles(index_path=tmp_path / "session_index.jsonl").is_usable(session_id)
