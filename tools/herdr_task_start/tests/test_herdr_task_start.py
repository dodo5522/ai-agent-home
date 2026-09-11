import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from herdr_task_state.model import HerdrReference, Task, TaskState, Workstream
from herdr_task_state.store import StateStore

from herdr_task_start import TaskStarter, TaskStartError
from herdr_task_start.cli import main as start_main
from herdr_task_start.herdr import (
    CreatedResources,
    HerdrClient,
    PaneInfo,
    TabInfo,
    WorkspaceInfo,
    _HerdrOperations,
)
from herdr_task_start.identity import load_issue_title, resolve_repository, short_title
from herdr_task_start.runner import CommandResult
from herdr_task_start.start import (
    TaskStartResolution,
)


@dataclass
class StubRunner:
    responses: dict[tuple[str, ...], CommandResult] = field(default_factory=dict)
    calls: list[tuple[tuple[str, ...], Path | None]] = field(default_factory=list)

    def run(self, arguments: Sequence[str], cwd: Path | None = None) -> CommandResult:
        command = tuple(arguments)
        self.calls.append((command, cwd))
        try:
            return self.responses[command]
        except KeyError as error:
            raise AssertionError(f"unexpected command: {command}") from error

    def respond(self, arguments: Sequence[str], result: CommandResult) -> None:
        self.responses[tuple(arguments)] = result


@dataclass
class FakeHerdr(_HerdrOperations):
    calls: list[tuple[str, ...]] = field(default_factory=list)
    workspaces: dict[str, WorkspaceInfo] = field(default_factory=dict)
    tabs: dict[str, TabInfo] = field(default_factory=dict)
    panes: dict[str, list[PaneInfo]] = field(default_factory=dict)
    next_workspace: CreatedResources = CreatedResources("w9", "w9:t2", "w9:p3")
    next_tab: CreatedResources = CreatedResources("w9", "w9:t3", "w9:p4")
    fail_create: bool = False
    fail_rename: bool = False

    def workspace_get(self, workspace_id: str) -> WorkspaceInfo:
        self.calls.append(("workspace", "get", workspace_id))
        try:
            return self.workspaces[workspace_id]
        except KeyError as error:
            raise TaskStartError("workspace is stale") from error

    def workspace_create(self, label: str, cwd: Path) -> CreatedResources:
        self.calls.append(("workspace", "create", label, str(cwd), "--no-focus"))
        if self.fail_create:
            raise TaskStartError("workspace create failed")
        created = self.next_workspace
        self.workspaces[created.workspace_id] = WorkspaceInfo(created.workspace_id, label)
        self.tabs[created.tab_id] = TabInfo(created.tab_id, created.workspace_id, "1")
        self.panes[created.tab_id] = [PaneInfo(created.pane_id, created.tab_id)]
        return created

    def workspace_close(self, workspace_id: str) -> None:
        self.calls.append(("workspace", "close", workspace_id))

    def tab_get(self, tab_id: str) -> TabInfo:
        self.calls.append(("tab", "get", tab_id))
        try:
            return self.tabs[tab_id]
        except KeyError as error:
            raise TaskStartError("tab is stale") from error

    def tab_create(self, workspace_id: str, label: str, cwd: Path) -> CreatedResources:
        self.calls.append(("tab", "create", workspace_id, label, str(cwd), "--no-focus"))
        created = self.next_tab
        self.tabs[created.tab_id] = TabInfo(created.tab_id, workspace_id, label)
        self.panes[created.tab_id] = [PaneInfo(created.pane_id, created.tab_id)]
        return CreatedResources(workspace_id, created.tab_id, created.pane_id)

    def tab_rename(self, tab_id: str, label: str) -> TabInfo:
        self.calls.append(("tab", "rename", tab_id, label))
        if self.fail_rename:
            raise TaskStartError("tab rename failed")
        current = self.tabs[tab_id]
        renamed = TabInfo(tab_id, current.workspace_id, label)
        self.tabs[tab_id] = renamed
        return renamed

    def tab_close(self, tab_id: str) -> None:
        self.calls.append(("tab", "close", tab_id))

    def panes_for_workspace(self, workspace_id: str, tab_id: str) -> list[PaneInfo]:
        self.calls.append(("pane", "list", workspace_id, tab_id))
        return list(self.panes.get(tab_id, []))

    def count_calls(self, *prefix: str) -> int:
        return sum(call[: len(prefix)] == prefix for call in self.calls)

    def was_called(self, *prefix: str) -> bool:
        return self.count_calls(*prefix) > 0

    def set_panes(self, tab_id: str, pane_ids: Sequence[str]) -> None:
        self.panes[tab_id] = [PaneInfo(pane_id, tab_id) for pane_id in pane_ids]


def test_herdr_implementations_explicitly_extend_operations_protocol() -> None:
    assert _HerdrOperations in HerdrClient.__bases__
    assert _HerdrOperations in FakeHerdr.__bases__


@dataclass
class StartFixture:
    tmp_path: Path
    runner: StubRunner
    herdr: FakeHerdr
    state_path: Path

    def run(self, issue_number: int = 32) -> TaskStartResolution:
        return TaskStarter(self.state_path, runner=self.runner, herdr=self.herdr).start(
            issue_number, self.tmp_path
        )

    def state(self) -> TaskState:
        return StateStore(self.state_path).read()

    def state_bytes(self) -> bytes:
        return self.state_path.read_bytes() if self.state_path.exists() else b""

    def write_state_with_ids(
        self, workspace_id: str, tab_id: str, pane_id: str, issue_number: int = 32
    ) -> None:
        task = Task(
            repository="dodo5522/ai-agent-home",
            issue_number=issue_number,
            title="old title",
            herdr=HerdrReference(
                workspace_id=workspace_id, workspace_label="dodo5522/ai-agent-home"
            ),
            workstreams={
                "main": Workstream(
                    tab_id=tab_id,
                    tab_label="old tab",
                    pane_ids={"root": pane_id},
                )
            },
        )
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            TaskState(version=1, tasks={f"dodo5522/ai-agent-home#{issue_number}": task}).to_json(),
            encoding="utf-8",
        )


@pytest.fixture
def start_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> StartFixture:
    monkeypatch.setenv("HERDR_ENV", "1")
    runner = StubRunner()
    runner.respond(
        ["git", "-C", str(tmp_path), "remote", "get-url", "origin"],
        CommandResult(0, "git@github.com:Dodo5522/Ai-Agent-Home.git\n", ""),
    )
    runner.respond(
        ["gh", "issue", "view", "32", "--repo", "dodo5522/ai-agent-home", "--json", "title"],
        CommandResult(0, json.dumps({"title": "Herdr task-start"}), ""),
    )
    return StartFixture(tmp_path, runner, FakeHerdr(), tmp_path / "state.json")


def test_resolve_repository_accepts_https_and_ssh_remotes() -> None:
    for remote in (
        "https://github.com/Dodo5522/Ai-Agent-Home.git",
        "git@github.com:Dodo5522/Ai-Agent-Home.git",
    ):
        runner = StubRunner()
        runner.respond(
            ["git", "-C", "/tmp/repo", "remote", "get-url", "origin"],
            CommandResult(0, remote + "\n", ""),
        )

        assert resolve_repository(Path("/tmp/repo"), runner) == "dodo5522/ai-agent-home"


def test_load_issue_title_uses_repository_and_json() -> None:
    runner = StubRunner()
    runner.respond(
        ["gh", "issue", "view", "32", "--repo", "dodo5522/ai-agent-home", "--json", "title"],
        CommandResult(0, json.dumps({"title": "  Herdr   task-start  "}), ""),
    )

    assert load_issue_title("dodo5522/ai-agent-home", 32, runner) == "  Herdr   task-start  "


def test_short_title_collapses_whitespace_and_limits() -> None:
    assert short_title("  Herdr\nSpace   reconciliation ") == "Herdr Space reconciliation"
    assert len(short_title("x" * 61)) == 60
    assert short_title("x" * 61).endswith("…")


def test_resolve_repository_rejects_non_github_remote() -> None:
    runner = StubRunner()
    runner.respond(
        ["git", "-C", "/tmp/repo", "remote", "get-url", "origin"],
        CommandResult(0, "https://example.invalid/repo.git\n", ""),
    )

    with pytest.raises(TaskStartError, match="GitHub remote"):
        resolve_repository(Path("/tmp/repo"), runner)


def test_failed_git_does_not_echo_command_output() -> None:
    runner = StubRunner()
    runner.respond(
        ["git", "-C", "/tmp/repo", "remote", "get-url", "origin"],
        CommandResult(1, "secret stdout", "secret stderr"),
    )

    with pytest.raises(TaskStartError) as error:
        resolve_repository(Path("/tmp/repo"), runner)

    assert "secret" not in str(error.value)


@pytest.mark.parametrize("stdout", ["{}", "not json"])
def test_invalid_issue_title_response_is_rejected(stdout: str) -> None:
    runner = StubRunner()
    runner.respond(
        ["gh", "issue", "view", "32", "--repo", "dodo5522/ai-agent-home", "--json", "title"],
        CommandResult(0, stdout, ""),
    )

    with pytest.raises(TaskStartError, match="Issue title"):
        load_issue_title("dodo5522/ai-agent-home", 32, runner)


def test_failed_issue_lookup_does_not_echo_command_output() -> None:
    runner = StubRunner()
    runner.respond(
        ["gh", "issue", "view", "32", "--repo", "dodo5522/ai-agent-home", "--json", "title"],
        CommandResult(1, "secret stdout", "secret stderr"),
    )

    with pytest.raises(TaskStartError) as error:
        load_issue_title("dodo5522/ai-agent-home", 32, runner)

    assert "secret" not in str(error.value)


def test_workspace_get_parses_identity() -> None:
    runner = StubRunner()
    runner.respond(
        ["herdr", "workspace", "get", "w9"],
        CommandResult(
            0,
            json.dumps({"result": {"workspace": {"workspace_id": "w9", "label": "owner/repo"}}}),
            "",
        ),
    )

    assert HerdrClient(runner).workspace_get("w9") == WorkspaceInfo("w9", "owner/repo")


def test_workspace_create_parses_ids_and_no_focus() -> None:
    runner = StubRunner()
    runner.respond(
        [
            "herdr",
            "workspace",
            "create",
            "--label",
            "owner/repo",
            "--cwd",
            "/tmp/work",
            "--no-focus",
        ],
        CommandResult(
            0,
            json.dumps(
                {
                    "result": {
                        "workspace": {"workspace_id": "w9", "label": "owner/repo"},
                        "tab": {"tab_id": "w9:t2", "workspace_id": "w9", "label": "1"},
                        "root_pane": {"pane_id": "w9:p3", "tab_id": "w9:t2"},
                    }
                }
            ),
            "",
        ),
    )

    assert HerdrClient(runner).workspace_create(
        "owner/repo", Path("/tmp/work")
    ) == CreatedResources("w9", "w9:t2", "w9:p3")


def test_tab_operations_parse_identity_and_use_no_focus() -> None:
    runner = StubRunner()
    runner.respond(
        ["herdr", "tab", "get", "w9:t2"],
        CommandResult(
            0,
            json.dumps(
                {"result": {"tab": {"tab_id": "w9:t2", "workspace_id": "w9", "label": "32 title"}}}
            ),
            "",
        ),
    )
    runner.respond(
        [
            "herdr",
            "tab",
            "create",
            "--workspace",
            "w9",
            "--cwd",
            "/tmp/work",
            "--label",
            "32 title",
            "--no-focus",
        ],
        CommandResult(
            0,
            json.dumps(
                {
                    "result": {
                        "tab": {"tab_id": "w9:t3", "workspace_id": "w9", "label": "32 title"},
                        "root_pane": {"pane_id": "w9:p4", "tab_id": "w9:t3"},
                    }
                }
            ),
            "",
        ),
    )
    runner.respond(
        ["herdr", "tab", "rename", "w9:t2", "32 title"],
        CommandResult(
            0,
            json.dumps(
                {"result": {"tab": {"tab_id": "w9:t2", "workspace_id": "w9", "label": "32 title"}}}
            ),
            "",
        ),
    )
    client = HerdrClient(runner)

    assert client.tab_get("w9:t2") == TabInfo("w9:t2", "w9", "32 title")
    assert client.tab_create("w9", "32 title", Path("/tmp/work")) == CreatedResources(
        "w9", "w9:t3", "w9:p4"
    )
    assert client.tab_rename("w9:t2", "32 title") == TabInfo("w9:t2", "w9", "32 title")


def test_panes_for_workspace_filters_by_tab() -> None:
    runner = StubRunner()
    runner.respond(
        ["herdr", "pane", "list", "--workspace", "w9"],
        CommandResult(
            0,
            json.dumps(
                {
                    "result": {
                        "panes": [
                            {"pane_id": "w9:p1", "tab_id": "w9:t2"},
                            {"pane_id": "w9:p2", "tab_id": "w9:t3"},
                        ]
                    }
                }
            ),
            "",
        ),
    )

    assert HerdrClient(runner).panes_for_workspace("w9", "w9:t2") == [PaneInfo("w9:p1", "w9:t2")]


def test_herdr_failures_and_malformed_json_are_rejected_without_echoing_output() -> None:
    runner = StubRunner()
    runner.respond(
        ["herdr", "workspace", "get", "w9"],
        CommandResult(1, "secret stdout", "secret stderr"),
    )
    with pytest.raises(TaskStartError) as error:
        HerdrClient(runner).workspace_get("w9")
    assert "secret" not in str(error.value)

    malformed = StubRunner()
    malformed.respond(
        ["herdr", "workspace", "get", "w9"],
        CommandResult(0, "not json", ""),
    )
    with pytest.raises(TaskStartError, match="JSON"):
        HerdrClient(malformed).workspace_get("w9")


def test_herdr_response_missing_identity_is_rejected() -> None:
    runner = StubRunner()
    runner.respond(
        ["herdr", "workspace", "get", "w9"],
        CommandResult(0, json.dumps({"result": {"workspace": {"label": "owner/repo"}}}), ""),
    )

    with pytest.raises(TaskStartError, match="workspace"):
        HerdrClient(runner).workspace_get("w9")


def test_first_start_creates_and_persists(start_fixture: StartFixture) -> None:
    result = start_fixture.run(32)

    assert result.workspace_id == "w9"
    assert result.tab_id == "w9:t2"
    assert result.pane_id == "w9:p3"
    assert result.task.workstreams["main"].pane_ids == {"root": "w9:p3"}
    assert start_fixture.state().tasks["dodo5522/ai-agent-home#32"] == result.task


def test_second_start_reuses_without_duplicate_create(start_fixture: StartFixture) -> None:
    first = start_fixture.run(32)
    second = start_fixture.run(32)

    assert second.task == first.task
    assert start_fixture.herdr.count_calls("workspace", "create") == 1
    assert start_fixture.herdr.count_calls("tab", "create") == 0


def test_stale_state_does_not_import_label_only_resource(start_fixture: StartFixture) -> None:
    start_fixture.write_state_with_ids("w-stale", "w-stale:t1", "w-stale:p1")
    start_fixture.herdr.workspaces["w-unmanaged"] = WorkspaceInfo(
        "w-unmanaged", "dodo5522/ai-agent-home"
    )
    start_fixture.herdr.next_workspace = CreatedResources("w-new", "w-new:t1", "w-new:p1")

    result = start_fixture.run(32)

    assert result.workspace_id == "w-new"
    assert start_fixture.herdr.was_called("workspace", "create")
    assert not start_fixture.herdr.was_called("workspace", "rename")


def test_multiple_panes_fail_without_state_update(start_fixture: StartFixture) -> None:
    first = start_fixture.run(32)
    before = start_fixture.state_bytes()
    start_fixture.herdr.set_panes(first.tab_id, ["w9:p3", "w9:p4"])

    with pytest.raises(TaskStartError, match="exactly one pane"):
        start_fixture.run(32)

    assert start_fixture.state_bytes() == before


def test_workspace_from_another_task_is_reused(start_fixture: StartFixture) -> None:
    workspace = WorkspaceInfo("w9", "dodo5522/ai-agent-home")
    start_fixture.herdr.workspaces[workspace.workspace_id] = workspace
    start_fixture.herdr.next_tab = CreatedResources("w9", "w9:t3", "w9:p4")
    other = Task(
        repository="dodo5522/ai-agent-home",
        issue_number=31,
        herdr=HerdrReference(workspace_id="w9", workspace_label=workspace.label),
        workstreams={"main": Workstream()},
    )
    start_fixture.state_path.parent.mkdir(parents=True, exist_ok=True)
    start_fixture.state_path.write_text(
        TaskState(version=1, tasks={"dodo5522/ai-agent-home#31": other}).to_json(),
        encoding="utf-8",
    )

    result = start_fixture.run(32)

    assert result.workspace_id == "w9"
    assert start_fixture.herdr.count_calls("workspace", "create") == 0
    assert start_fixture.herdr.count_calls("tab", "create") == 1


def test_existing_task_metadata_is_preserved(start_fixture: StartFixture) -> None:
    start_fixture.write_state_with_ids("w9", "w9:t2", "w9:p3")
    start_fixture.herdr.workspaces["w9"] = WorkspaceInfo("w9", "dodo5522/ai-agent-home")
    start_fixture.herdr.tabs["w9:t2"] = TabInfo("w9:t2", "w9", "32 Herdr task-start")
    start_fixture.herdr.set_panes("w9:t2", ["w9:p3"])
    current = start_fixture.state().tasks["dodo5522/ai-agent-home#32"]
    current = current.model_copy(
        update={
            "metadata": {"keep": True},
            "workstreams": {**current.workstreams, "review": Workstream(branch="review")},
        }
    )
    start_fixture.state_path.write_text(
        TaskState(version=1, tasks={"dodo5522/ai-agent-home#32": current}).to_json(),
        encoding="utf-8",
    )

    result = start_fixture.run(32)

    assert result.task.model_extra["metadata"] == {"keep": True}
    assert result.task.workstreams["review"].branch == "review"


def test_missing_herdr_environment_is_rejected(
    start_fixture: StartFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HERDR_ENV")

    with pytest.raises(TaskStartError, match="HERDR_ENV"):
        start_fixture.run(32)


def test_failed_workspace_create_leaves_state_absent(start_fixture: StartFixture) -> None:
    start_fixture.herdr.fail_create = True

    with pytest.raises(TaskStartError, match="workspace create"):
        start_fixture.run(32)

    assert not start_fixture.state_path.exists()


def test_failed_tab_rename_leaves_state_absent(start_fixture: StartFixture) -> None:
    start_fixture.herdr.fail_rename = True

    with pytest.raises(TaskStartError, match="tab rename"):
        start_fixture.run(32)

    assert not start_fixture.state_path.exists()


def test_failed_state_write_rolls_back_created_workspace(
    start_fixture: StartFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_put(self: StateStore, key: str, task: Task) -> Task:
        raise TaskStartError("state write failed")

    monkeypatch.setattr(StateStore, "put", fail_put)

    with pytest.raises(TaskStartError, match="state write failed"):
        start_fixture.run(32)

    assert not start_fixture.state_path.exists()
    assert start_fixture.herdr.was_called("workspace", "close", "w9")


def test_start_cli_help_describes_issue_and_cwd(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        start_main(["--help"])

    assert error.value.code == 0
    output = capsys.readouterr().out
    assert "ISSUE_NUMBER" in output
    assert "--cwd" in output


def test_start_cli_rejects_invalid_issue(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        start_main(["not-a-number"])

    assert error.value.code == 2
    assert "ISSUE_NUMBER" in capsys.readouterr().err


def test_start_cli_maps_missing_herdr_environment_to_runtime_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("HERDR_ENV", raising=False)

    assert start_main(["32", "--cwd", str(tmp_path)]) == 1
    assert "HERDR_ENV" in capsys.readouterr().err
