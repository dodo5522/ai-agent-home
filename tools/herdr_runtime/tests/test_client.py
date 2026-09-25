import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from herdr_runtime import CommandResult, HerdrClient, HerdrError


@dataclass
class RecordingRunner:
    responses: dict[tuple[str, ...], CommandResult] = field(default_factory=dict)
    calls: list[tuple[str, ...]] = field(default_factory=list)

    def run(
        self,
        arguments: Sequence[str],
        cwd: Path | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> CommandResult:
        del cwd, environment
        command = tuple(arguments)
        self.calls.append(command)
        return self.responses[command]


def result(payload: object) -> CommandResult:
    return CommandResult(0, json.dumps({"result": payload}), "")


def test_invalid_json_is_a_typed_herdr_error() -> None:
    runner = RecordingRunner({("herdr", "workspace", "list"): CommandResult(0, "bad", "")})

    with pytest.raises(HerdrError, match="invalid JSON"):
        HerdrClient(runner).workspace.list()


def test_workspace_list_preserves_identity() -> None:
    runner = RecordingRunner(
        {
            ("herdr", "workspace", "list"): result(
                {"workspaces": [{"workspace_id": "w16", "label": "owner/repo"}]}
            )
        }
    )

    assert HerdrClient(runner).workspace.list()[0].workspace_id == "w16"


def test_agent_start_targets_explicit_pane() -> None:
    command = (
        "herdr",
        "agent",
        "start",
        "codex-main",
        "--kind",
        "codex",
        "--pane",
        "w16:p2",
    )
    runner = RecordingRunner(
        {
            command: result(
                {
                    "agent": {
                        "agent": "codex",
                        "name": "codex-main",
                        "pane_id": "w16:p2",
                        "workspace_id": "w16",
                        "cwd": "/work/main",
                    }
                }
            )
        }
    )

    started = HerdrClient(runner).agent.start("codex-main", "w16:p2")

    assert started.name == "codex-main"
    assert runner.calls == [command]


def test_agent_decodes_codex_session_id() -> None:
    command = ("herdr", "agent", "list")
    runner = RecordingRunner(
        {
            command: result(
                {
                    "agents": [
                        {
                            "agent": "codex",
                            "name": "codex-main",
                            "pane_id": "w1:p1",
                            "workspace_id": "w1",
                            "cwd": "/work/main",
                            "agent_session": {"agent": "codex", "kind": "id", "value": "session-a"},
                        }
                    ]
                }
            )
        }
    )

    agent = HerdrClient(runner).agent.find("codex-main")

    assert agent is not None
    assert agent.codex_session_id == "session-a"


def test_agent_start_passes_exact_resume_id() -> None:
    command = (
        "herdr",
        "agent",
        "start",
        "codex-main",
        "--kind",
        "codex",
        "--pane",
        "w1:p1",
        "--",
        "resume",
        "session-a",
    )
    runner = RecordingRunner(
        {
            command: result(
                {
                    "agent": {
                        "agent": "codex",
                        "name": "codex-main",
                        "pane_id": "w1:p1",
                        "workspace_id": "w1",
                        "cwd": "/work/main",
                    }
                }
            )
        }
    )

    HerdrClient(runner).agent.start("codex-main", "w1:p1", native_args=("resume", "session-a"))

    assert runner.calls == [command]


def test_agent_prompt_targets_exact_name() -> None:
    command = ("herdr", "agent", "prompt", "codex-main", "start issue 9")
    runner = RecordingRunner({command: result({})})

    HerdrClient(runner).agent.prompt("codex-main", "start issue 9")

    assert runner.calls == [command]
