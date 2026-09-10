import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from herdr_task_state import model as model_module
from herdr_task_state.model import (
    StateValidationError,
    Task,
    TaskKey,
    TaskState,
    Workstream,
)
from herdr_task_state.store import StateFileLock

TASK_KEY = "dodo5522/ai-agent-home#30"


@pytest.fixture
def complete_state() -> TaskState:
    return TaskState.model_validate(
        {
            "version": 1,
            "tasks": {
                TASK_KEY: {
                    "repository": "dodo5522/ai-agent-home",
                    "issue_number": 30,
                    "title": "Herdr",
                    "herdr": {"workspace_id": "wJ"},
                    "workstreams": {
                        "main": {
                            "worktree": "/tmp/work",
                            "pull_requests": [42],
                            "pane_ids": {"implementer": "wJ:p5"},
                            "agents": {"implementer": {"name": "agent"}},
                        }
                    },
                }
            },
        }
    )


def test_parses_task_keys() -> None:
    assert TaskKey.parse(TASK_KEY) == TaskKey("dodo5522/ai-agent-home", 30)
    for value in (
        "Dodo5522/ai-agent-home#30",
        "dodo5522/ai-agent-home#030",
        "dodo5522/ai-agent-home#30\n",
    ):
        with pytest.raises(StateValidationError):
            TaskKey.parse(value)


def test_workstream_key_validation_is_model_owned() -> None:
    assert not hasattr(model_module, "parse_workstream_key")
    Task(
        repository="dodo5522/ai-agent-home",
        issue_number=30,
        workstreams={"main": {}, "review-2": {}},
    )
    with pytest.raises(ValidationError):
        Task(
            repository="dodo5522/ai-agent-home",
            issue_number=30,
            workstreams={"main": {}, "Invalid_Key": {}},
        )
    with pytest.raises(ValidationError):
        Workstream(pane_ids={"Invalid_Key": "pane"})
    with pytest.raises(ValidationError):
        Workstream(agents={"Invalid_Key": {"name": "agent"}})


def test_model_is_the_json_round_trip_boundary(complete_state: TaskState) -> None:
    parsed = TaskState.parse(complete_state.to_json())
    assert parsed.tasks[TASK_KEY].repository == "dodo5522/ai-agent-home"
    assert Task.parse(TASK_KEY, parsed.tasks[TASK_KEY].to_json()).issue_number == 30


@pytest.mark.parametrize(
    "payload",
    [
        '{"version": true, "tasks": {}}',
        '{"version": 1.0, "tasks": {}}',
        '{"version": 1, "tasks": {}, "metadata": NaN}',
    ],
)
def test_rejects_non_strict_json_values(payload: str) -> None:
    with pytest.raises(StateValidationError):
        TaskState.parse(payload)


def test_rejects_missing_main_and_explicit_null(complete_state: TaskState) -> None:
    document = json.loads(complete_state.to_json())
    del document["tasks"][TASK_KEY]["workstreams"]["main"]
    with pytest.raises(ValidationError):
        TaskState.model_validate(document)

    document = json.loads(complete_state.to_json())
    document["tasks"][TASK_KEY]["workstreams"]["main"]["tab_id"] = None
    with pytest.raises(ValidationError):
        TaskState.model_validate(document)


def test_rejects_identity_mismatch(complete_state: TaskState) -> None:
    document = json.loads(complete_state.to_json())
    document["tasks"][TASK_KEY]["issue_number"] = 31
    with pytest.raises(StateValidationError):
        TaskState.parse(json.dumps(document))


def test_validation_errors_do_not_echo_input_values() -> None:
    secret = "session-secret-value"
    payload = json.dumps(
        {
            "version": 1,
            "tasks": {
                TASK_KEY: {
                    "repository": "dodo5522/ai-agent-home",
                    "issue_number": 30,
                    "workstreams": {"main": {"agents": {"worker": {"name": {"secret": secret}}}}},
                }
            },
        }
    )
    with pytest.raises(StateValidationError) as error:
        TaskState.parse(payload)
    assert secret not in str(error.value)


def test_preserves_unknown_fields(complete_state: TaskState) -> None:
    document = json.loads(complete_state.to_json())
    document["future"] = {"enabled": True}
    parsed = TaskState.parse(json.dumps(document))
    assert json.loads(parsed.to_json())["future"] == {"enabled": True}


def test_workstream_constraints_are_field_level() -> None:
    assert Workstream(worktree="/tmp/work", pull_requests=[1, 2])
    with pytest.raises(ValidationError):
        Workstream(worktree="relative")
    with pytest.raises(ValidationError):
        Workstream(pull_requests=[1, 1])


def test_task_model_requires_main_workstream() -> None:
    with pytest.raises(ValidationError):
        Task(repository="dodo5522/ai-agent-home", issue_number=30, workstreams={})


def test_state_file_lock_releases_after_action_failure(tmp_path: Path) -> None:
    lock = StateFileLock(tmp_path / "state.json")

    with pytest.raises(RuntimeError, match="action failed"):
        with lock.locked():
            raise RuntimeError("action failed")

    with lock.locked():
        pass
