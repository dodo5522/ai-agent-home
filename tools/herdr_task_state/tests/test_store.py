import json
from pathlib import Path

import pytest

from herdr_task_state.model import StateValidationError, Task
from herdr_task_state.store import StateStore

TASK_KEY = "dodo5522/ai-agent-home#30"


def replacement_task() -> Task:
    return Task(
        repository="dodo5522/ai-agent-home",
        issue_number=30,
        workstreams={"main": {}},
    )


def write_v1_state(tmp_path: Path) -> Path:
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "tasks": {},
                "future_metadata": {"keep": True},
            }
        ),
        encoding="utf-8",
    )
    return path


def test_put_migrates_v1_and_preserves_unknown_fields(tmp_path: Path) -> None:
    path = write_v1_state(tmp_path)

    StateStore(path).put(TASK_KEY, replacement_task())

    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["version"] == 2
    assert document["persistent_agents"] == {}
    assert document["future_metadata"] == {"keep": True}


def test_failed_migration_preserves_original_bytes(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text('{"version":1,"tasks":{},"metadata":NaN}', encoding="utf-8")
    before = path.read_bytes()

    with pytest.raises(StateValidationError):
        StateStore(path).put(TASK_KEY, replacement_task())

    assert path.read_bytes() == before
