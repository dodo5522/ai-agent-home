"""Agent-related Herdr runtime adapter tests."""

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
        command = tuple(arguments)
        self.calls.append(command)
        try:
            return self.responses[command]
        except KeyError as error:
            raise AssertionError(f"unexpected command: {command}") from error

    def respond(self, arguments: Sequence[str], result: CommandResult) -> None:
        self.responses[tuple(arguments)] = result


def herdr_result(payload: object) -> CommandResult:
    return CommandResult(0, json.dumps({"result": payload}), "")


def test_lists_named_agents_with_valid_identity() -> None:
    runner = RecordingRunner()
    runner.respond(
        ["herdr", "agent", "list"],
        herdr_result(
            {
                "agents": [
                    {
                        "agent": "codex-main",
                        "agent_status": "working",
                        "agent_session": {"agent": "codex", "kind": "id"},
                        "pane_id": "w16:p2",
                        "workspace_id": "w16",
                        "cwd": "/work/main",
                    }
                ]
            }
        ),
    )

    agents = HerdrClient(runner).agents()

    assert agents[0].name == "codex-main"
    assert agents[0].kind == "codex"
    assert agents[0].pane_id == "w16:p2"
    assert agents[0].workspace_id == "w16"
    assert agents[0].cwd == Path("/work/main")


def test_rejects_agent_identity_mismatch() -> None:
    runner = RecordingRunner()
    runner.respond(
        ["herdr", "agent", "list"],
        herdr_result(
            {
                "agents": [
                    {
                        "agent": "",
                        "agent_session": {"agent": "codex"},
                        "pane_id": "w16:p2",
                        "workspace_id": "w16",
                        "cwd": "/work/main",
                    }
                ]
            }
        ),
    )

    with pytest.raises(HerdrError, match="agent"):
        HerdrClient(runner).agents()


def test_lists_panes_with_cwd_and_workspace_identity() -> None:
    runner = RecordingRunner()
    runner.respond(
        ["herdr", "pane", "list", "--workspace", "w16"],
        herdr_result(
            {
                "panes": [
                    {
                        "pane_id": "w16:p2",
                        "tab_id": "w16:t2",
                        "workspace_id": "w16",
                        "cwd": "/work/main",
                    }
                ]
            }
        ),
    )

    panes = HerdrClient(runner).panes("w16")

    assert panes[0].pane_id == "w16:p2"
    assert panes[0].workspace_id == "w16"
    assert panes[0].cwd == Path("/work/main")


def test_starts_agent_on_explicit_pane_and_validates_result() -> None:
    runner = RecordingRunner()
    runner.respond(
        ["herdr", "agent", "start", "codex-main", "--kind", "codex", "--pane", "w16:p2"],
        herdr_result(
            {
                "agent": {
                    "agent": "codex-main",
                    "agent_session": {"agent": "codex"},
                    "pane_id": "w16:p2",
                    "workspace_id": "w16",
                    "cwd": "/work/main",
                }
            }
        ),
    )

    started = HerdrClient(runner).agent_start("codex-main", "w16:p2")

    assert started.name == "codex-main"
    assert runner.calls == [
        ("herdr", "agent", "start", "codex-main", "--kind", "codex", "--pane", "w16:p2")
    ]


def test_prompts_exact_agent_name_without_focus_targeting() -> None:
    runner = RecordingRunner()
    runner.respond(
        ["herdr", "agent", "prompt", "codex-main", "start issue 9"],
        herdr_result({}),
    )

    HerdrClient(runner).agent_prompt("codex-main", "start issue 9")

    assert runner.calls == [("herdr", "agent", "prompt", "codex-main", "start issue 9")]
