import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from herdr_runtime import (
    CommandResult,
    CreatedResources,
    HerdrClient,
    HerdrError,
    PaneInfo,
    TabInfo,
    WorkspaceInfo,
)
from herdr_task_state.model import (
    AgentReference,
    HerdrReference,
    Task,
    TaskKey,
    TaskState,
    Workstream,
)
from herdr_task_state.store import StateStore

from herdr_task_lifecycle.cli import main as lifecycle_main
from herdr_task_lifecycle.commands.start.implementer import TaskAgentStarter
from herdr_task_lifecycle.commands.start.service import TaskStarter, TaskStartResolution
from herdr_task_lifecycle.errors import LifecycleError
from herdr_task_lifecycle.herdr_operations import HerdrOperations
from herdr_task_lifecycle.identity import load_issue_title, resolve_repository, short_title


@dataclass
class RecordingRunner:
    token: str | None = "test-installation-token"
    responses: dict[tuple[str, ...], CommandResult] = field(default_factory=dict)
    calls: list[tuple[tuple[str, ...], Path | None, Mapping[str, str] | None]] = field(
        default_factory=list
    )
    gh_environment: dict[str, str] | None = None

    def run(
        self,
        arguments: Sequence[str],
        cwd: Path | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> CommandResult:
        command = tuple(arguments)
        self.calls.append((command, cwd, environment))
        if Path(command[0]).name == "get-github-app-token.py":
            if self.token is None:
                return CommandResult(1, "", "token generation failed")
            return CommandResult(0, f"{self.token}\n", "")
        if command[:3] == ("gh", "issue", "view"):
            self.gh_environment = dict(environment or {})
        try:
            return self.responses[command]
        except KeyError as error:
            raise AssertionError(f"unexpected command: {command}") from error

    def respond(self, arguments: Sequence[str], result: CommandResult) -> None:
        self.responses[tuple(arguments)] = result

    def respond_to_issue_lookup(
        self,
        *,
        returncode: int,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        self.respond(
            [
                "gh",
                "issue",
                "view",
                "33",
                "--repo",
                "dodo5522/ai-agent-home",
                "--json",
                "title",
            ],
            CommandResult(returncode, stdout, stderr),
        )


@dataclass
class FakeWorkspaceClient:
    owner: FakeHerdr

    def get(self, workspace_id: str) -> WorkspaceInfo:
        return self.owner.workspace_get(workspace_id)

    def create(self, label: str, cwd: Path) -> CreatedResources:
        return self.owner.workspace_create(label, cwd)

    def close(self, workspace_id: str) -> None:
        self.owner.workspace_close(workspace_id)


@dataclass
class FakeTabClient:
    owner: FakeHerdr

    def get(self, tab_id: str) -> TabInfo:
        return self.owner.tab_get(tab_id)

    def create(self, workspace_id: str, label: str, cwd: Path) -> CreatedResources:
        return self.owner.tab_create(workspace_id, label, cwd)

    def rename(self, tab_id: str, label: str) -> TabInfo:
        return self.owner.tab_rename(tab_id, label)

    def close(self, tab_id: str) -> None:
        self.owner.tab_close(tab_id)


@dataclass
class FakePaneClient:
    owner: FakeHerdr

    def for_tab(self, workspace_id: str, tab_id: str) -> list[PaneInfo]:
        return self.owner.panes_for_workspace(workspace_id, tab_id)


@dataclass
class FakeHerdr(HerdrOperations):
    calls: list[tuple[str, ...]] = field(default_factory=list)
    workspaces: dict[str, WorkspaceInfo] = field(default_factory=dict)
    tabs: dict[str, TabInfo] = field(default_factory=dict)
    panes: dict[str, list[PaneInfo]] = field(default_factory=dict)
    next_workspace: CreatedResources = CreatedResources("w9", "w9:t2", "w9:p3")
    next_tab: CreatedResources = CreatedResources("w9", "w9:t3", "w9:p4")
    fail_create: bool = False
    fail_rename: bool = False
    workspace: FakeWorkspaceClient = field(init=False)
    tab: FakeTabClient = field(init=False)
    pane: FakePaneClient = field(init=False)

    def __post_init__(self) -> None:
        self.workspace = FakeWorkspaceClient(self)
        self.tab = FakeTabClient(self)
        self.pane = FakePaneClient(self)

    def workspace_get(self, workspace_id: str) -> WorkspaceInfo:
        self.calls.append(("workspace", "get", workspace_id))
        try:
            return self.workspaces[workspace_id]
        except KeyError as error:
            raise LifecycleError("workspace is stale") from error

    def workspace_create(self, label: str, cwd: Path) -> CreatedResources:
        self.calls.append(("workspace", "create", label, str(cwd), "--no-focus"))
        if self.fail_create:
            raise LifecycleError("workspace create failed")
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
            raise LifecycleError("tab is stale") from error

    def tab_create(self, workspace_id: str, label: str, cwd: Path) -> CreatedResources:
        self.calls.append(("tab", "create", workspace_id, label, str(cwd), "--no-focus"))
        created = self.next_tab
        self.tabs[created.tab_id] = TabInfo(created.tab_id, workspace_id, label)
        self.panes[created.tab_id] = [PaneInfo(created.pane_id, created.tab_id)]
        return CreatedResources(workspace_id, created.tab_id, created.pane_id)

    def tab_rename(self, tab_id: str, label: str) -> TabInfo:
        self.calls.append(("tab", "rename", tab_id, label))
        if self.fail_rename:
            raise LifecycleError("tab rename failed")
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


@dataclass
class RecordingTaskAgentStarter:
    calls: list[tuple[str, str, str]] = field(default_factory=list)
    fail: bool = False

    def ensure_implementer(self, task_key: TaskKey, task: Task, pane_id: str) -> AgentReference:
        if self.fail:
            raise LifecycleError("Agent start failed")
        self.calls.append((str(task_key), task.title or "", pane_id))
        return AgentReference(name="codex-issue-32-test")


def test_fake_herdr_explicitly_extends_operations_protocol() -> None:
    assert HerdrOperations in FakeHerdr.__bases__


@dataclass
class StartFixture:
    tmp_path: Path
    runner: RecordingRunner
    herdr: FakeHerdr
    state_path: Path
    tasks_directory: Path
    task_root: Path
    worktree: Path
    git_common_dir: Path
    git_dir: Path
    primary_worktree: Path
    branch: str = "feat/issue-32-herdr-task-start"

    def run(
        self,
        issue_number: int = 32,
        cwd: Path | None = None,
        agent_starter: TaskAgentStarter | None = None,
    ) -> TaskStartResolution:
        return TaskStarter(
            self.state_path,
            runner=self.runner,
            herdr=self.herdr,
            task_roots_directory=self.tasks_directory,
            agent_starter=agent_starter,
        ).start(issue_number, cwd or self.worktree)

    def git_command(self, cwd: Path, *arguments: str) -> list[str]:
        return ["git", "-C", str(cwd), *arguments]

    def respond_worktree(
        self,
        cwd: Path,
        branch: str | None,
        *,
        git_dir: Path | None = None,
        inventory: str | None = None,
    ) -> None:
        self.runner.respond(
            self.git_command(cwd, "rev-parse", "--git-dir"),
            CommandResult(0, f"{git_dir or self.git_dir}\n", ""),
        )
        self.runner.respond(
            self.git_command(cwd, "rev-parse", "--git-common-dir"),
            CommandResult(0, f"{self.git_common_dir}\n", ""),
        )
        self.runner.respond(
            self.git_command(cwd, "symbolic-ref", "--quiet", "--short", "HEAD"),
            CommandResult(0 if branch else 1, f"{branch}\n" if branch else "", ""),
        )
        self.runner.respond(
            self.git_command(cwd, "worktree", "list", "--porcelain"),
            CommandResult(0, inventory or self.inventory(cwd, branch or "main"), ""),
        )

    def inventory(self, cwd: Path, branch: str) -> str:
        return (
            f"worktree {self.primary_worktree}\n"
            f"HEAD {'0' * 40}\n"
            "branch refs/heads/main\n\n"
            f"worktree {cwd}\n"
            f"HEAD {'1' * 40}\n"
            f"branch refs/heads/{branch}\n"
        )

    def use_second_valid_worktree(self, branch: str) -> Path:
        worktree = self.task_root / "replacement-worktree"
        worktree.mkdir()
        git_dir = self.git_common_dir / "worktrees" / "replacement"
        git_dir.mkdir(parents=True)
        self.respond_worktree(worktree, branch, git_dir=git_dir)
        self.runner.respond(
            self.git_command(worktree, "remote", "get-url", "origin"),
            CommandResult(0, "git@github.com:Dodo5522/Ai-Agent-Home.git\n", ""),
        )
        return worktree

    def make_managed_tab(self, workspace_id: str, tab_id: str, pane_id: str, label: str) -> None:
        self.herdr.workspaces[workspace_id] = WorkspaceInfo(workspace_id, "dodo5522/ai-agent-home")
        self.herdr.tabs[tab_id] = TabInfo(tab_id, workspace_id, label)
        self.herdr.set_panes(tab_id, [pane_id])

    def state(self) -> TaskState:
        return StateStore(self.state_path).read()

    def state_bytes(self) -> bytes:
        return self.state_path.read_bytes() if self.state_path.exists() else b""

    def write_state_with_ids(
        self,
        workspace_id: str,
        tab_id: str,
        pane_id: str,
        issue_number: int = 32,
        tab_label: str = "old tab",
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
                    tab_label=tab_label,
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
    runner = RecordingRunner()
    tasks_directory = tmp_path / "tasks"
    task_root = tasks_directory / "issue-32"
    worktree = task_root / "worktree"
    worktree.mkdir(parents=True)
    (task_root / ".codex-task-root").touch()
    git_common_dir = tmp_path / "repository" / ".git"
    git_dir = git_common_dir / "worktrees" / "issue-32"
    git_dir.mkdir(parents=True)
    fixture = StartFixture(
        tmp_path=tmp_path,
        runner=runner,
        herdr=FakeHerdr(),
        state_path=tmp_path / "state.json",
        tasks_directory=tasks_directory,
        task_root=task_root,
        worktree=worktree,
        git_common_dir=git_common_dir,
        git_dir=git_dir,
        primary_worktree=tmp_path / "repository",
    )
    fixture.respond_worktree(worktree, fixture.branch)
    runner.respond(
        ["git", "-C", str(worktree), "remote", "get-url", "origin"],
        CommandResult(0, "git@github.com:Dodo5522/Ai-Agent-Home.git\n", ""),
    )
    runner.respond(
        ["gh", "issue", "view", "32", "--repo", "dodo5522/ai-agent-home", "--json", "title"],
        CommandResult(0, json.dumps({"title": "Herdr task-start"}), ""),
    )
    return fixture


def test_resolve_repository_accepts_https_and_ssh_remotes() -> None:
    for remote in (
        "https://github.com/Dodo5522/Ai-Agent-Home.git",
        "git@github.com:Dodo5522/Ai-Agent-Home.git",
    ):
        runner = RecordingRunner()
        runner.respond(
            ["git", "-C", "/tmp/repo", "remote", "get-url", "origin"],
            CommandResult(0, remote + "\n", ""),
        )

        assert resolve_repository(Path("/tmp/repo"), runner) == "dodo5522/ai-agent-home"


def test_load_issue_title_uses_repository_and_json() -> None:
    runner = RecordingRunner()
    runner.respond(
        ["gh", "issue", "view", "32", "--repo", "dodo5522/ai-agent-home", "--json", "title"],
        CommandResult(0, json.dumps({"title": "  Herdr   task-start  "}), ""),
    )

    assert load_issue_title("dodo5522/ai-agent-home", 32, runner) == "  Herdr   task-start  "


def test_issue_lookup_uses_github_app_token_without_echoing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GH_TOKEN", raising=False)
    runner = RecordingRunner(token="test-installation-token")
    runner.respond_to_issue_lookup(returncode=1, stderr="authentication failed")

    with pytest.raises(LifecycleError, match="cannot load GitHub Issue title") as error:
        load_issue_title("dodo5522/ai-agent-home", 33, runner)

    assert runner.gh_environment is not None
    assert runner.gh_environment["GH_TOKEN"] == "test-installation-token"
    assert "test-installation-token" not in str(error.value)


def test_issue_lookup_preserves_caller_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GH_TOKEN", "caller-token")
    runner = RecordingRunner(token=None)
    runner.respond_to_issue_lookup(
        returncode=0,
        stdout=json.dumps({"title": "Use caller credentials"}),
    )

    assert load_issue_title("dodo5522/ai-agent-home", 33, runner) == "Use caller credentials"
    assert runner.gh_environment is not None
    assert runner.gh_environment["GH_TOKEN"] == "caller-token"
    assert all(Path(call[0][0]).name != "get-github-app-token.py" for call in runner.calls)


def test_short_title_collapses_whitespace_and_limits() -> None:
    assert short_title("  Herdr\nSpace   reconciliation ") == "Herdr Space reconciliation"
    assert len(short_title("x" * 61)) == 60
    assert short_title("x" * 61).endswith("…")


def test_resolve_repository_rejects_non_github_remote() -> None:
    runner = RecordingRunner()
    runner.respond(
        ["git", "-C", "/tmp/repo", "remote", "get-url", "origin"],
        CommandResult(0, "https://example.invalid/repo.git\n", ""),
    )

    with pytest.raises(LifecycleError, match="GitHub remote"):
        resolve_repository(Path("/tmp/repo"), runner)


def test_failed_git_does_not_echo_command_output() -> None:
    runner = RecordingRunner()
    runner.respond(
        ["git", "-C", "/tmp/repo", "remote", "get-url", "origin"],
        CommandResult(1, "secret stdout", "secret stderr"),
    )

    with pytest.raises(LifecycleError) as error:
        resolve_repository(Path("/tmp/repo"), runner)

    assert "secret" not in str(error.value)


@pytest.mark.parametrize("stdout", ["{}", "not json"])
def test_invalid_issue_title_response_is_rejected(stdout: str) -> None:
    runner = RecordingRunner()
    runner.respond(
        ["gh", "issue", "view", "32", "--repo", "dodo5522/ai-agent-home", "--json", "title"],
        CommandResult(0, stdout, ""),
    )

    with pytest.raises(LifecycleError, match="Issue title"):
        load_issue_title("dodo5522/ai-agent-home", 32, runner)


def test_failed_issue_lookup_does_not_echo_command_output() -> None:
    runner = RecordingRunner()
    runner.respond(
        ["gh", "issue", "view", "32", "--repo", "dodo5522/ai-agent-home", "--json", "title"],
        CommandResult(1, "secret stdout", "secret stderr"),
    )

    with pytest.raises(LifecycleError) as error:
        load_issue_title("dodo5522/ai-agent-home", 32, runner)

    assert "secret" not in str(error.value)


def test_workspace_get_parses_identity() -> None:
    runner = RecordingRunner()
    runner.respond(
        ["herdr", "workspace", "get", "w9"],
        CommandResult(
            0,
            json.dumps({"result": {"workspace": {"workspace_id": "w9", "label": "owner/repo"}}}),
            "",
        ),
    )

    assert HerdrClient(runner).workspace.get("w9") == WorkspaceInfo("w9", "owner/repo")


def test_workspace_create_parses_ids_and_no_focus() -> None:
    runner = RecordingRunner()
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

    assert HerdrClient(runner).workspace.create(
        "owner/repo", Path("/tmp/work")
    ) == CreatedResources("w9", "w9:t2", "w9:p3")


def test_tab_operations_parse_identity_and_use_no_focus() -> None:
    runner = RecordingRunner()
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

    assert client.tab.get("w9:t2") == TabInfo("w9:t2", "w9", "32 title")
    assert client.tab.create("w9", "32 title", Path("/tmp/work")) == CreatedResources(
        "w9", "w9:t3", "w9:p4"
    )
    assert client.tab.rename("w9:t2", "32 title") == TabInfo("w9:t2", "w9", "32 title")


def test_panes_for_workspace_filters_by_tab() -> None:
    runner = RecordingRunner()
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

    assert HerdrClient(runner).pane.for_tab("w9", "w9:t2") == [PaneInfo("w9:p1", "w9:t2")]


def test_herdr_failures_and_malformed_json_are_rejected_without_echoing_output() -> None:
    runner = RecordingRunner()
    runner.respond(
        ["herdr", "workspace", "get", "w9"],
        CommandResult(1, "secret stdout", "secret stderr"),
    )
    with pytest.raises(HerdrError) as error:
        HerdrClient(runner).workspace.get("w9")
    assert "secret" not in str(error.value)

    malformed = RecordingRunner()
    malformed.respond(
        ["herdr", "workspace", "get", "w9"],
        CommandResult(0, "not json", ""),
    )
    with pytest.raises(HerdrError, match="JSON"):
        HerdrClient(malformed).workspace.get("w9")


def test_herdr_response_missing_identity_is_rejected() -> None:
    runner = RecordingRunner()
    runner.respond(
        ["herdr", "workspace", "get", "w9"],
        CommandResult(0, json.dumps({"result": {"workspace": {"label": "owner/repo"}}}), ""),
    )

    with pytest.raises(HerdrError, match="workspace"):
        HerdrClient(runner).workspace.get("w9")


def test_first_start_creates_and_persists(start_fixture: StartFixture) -> None:
    result = start_fixture.run(32)

    assert result.workspace_id == "w9"
    assert result.tab_id == "w9:t2"
    assert result.pane_id == "w9:p3"
    assert result.task.workstreams["main"].pane_ids == {"root": "w9:p3"}
    assert start_fixture.state().tasks["dodo5522/ai-agent-home#32"] == result.task


def test_start_invokes_task_agent_and_persists_reference(start_fixture: StartFixture) -> None:
    agent_starter = RecordingTaskAgentStarter()

    result = start_fixture.run(32, agent_starter=agent_starter)

    assert agent_starter.calls == [("dodo5522/ai-agent-home#32", "Herdr task-start", "w9:p3")]
    assert result.task.workstreams["main"].agents == {
        "implementer": AgentReference(name="codex-issue-32-test")
    }


def test_restarting_task_does_not_duplicate_task_agent(start_fixture: StartFixture) -> None:
    agent_starter = RecordingTaskAgentStarter()

    start_fixture.run(32, agent_starter=agent_starter)
    result = start_fixture.run(32, agent_starter=agent_starter)

    assert len(agent_starter.calls) == 2
    assert result.task.workstreams["main"].agents == {
        "implementer": AgentReference(name="codex-issue-32-test")
    }


def test_failed_task_agent_start_keeps_resources_for_retry(start_fixture: StartFixture) -> None:
    agent_starter = RecordingTaskAgentStarter(fail=True)

    with pytest.raises(LifecycleError, match="Agent start"):
        start_fixture.run(32, agent_starter=agent_starter)

    assert (
        start_fixture.state().tasks["dodo5522/ai-agent-home#32"].workstreams["main"].agents is None
    )
    assert not start_fixture.herdr.was_called("workspace", "close", "w9")


def test_first_start_persists_worktree_branch_and_hash_label(start_fixture: StartFixture) -> None:
    result = start_fixture.run(32)
    main = result.task.workstreams["main"]

    assert main.worktree == str(start_fixture.worktree)
    assert main.branch == "feat/issue-32-herdr-task-start"
    assert main.tab_label == "#32 Herdr task-start"


def test_legacy_task_is_upgraded_with_worktree_registration(start_fixture: StartFixture) -> None:
    start_fixture.write_state_with_ids("w9", "w9:t2", "w9:p3")
    start_fixture.make_managed_tab("w9", "w9:t2", "w9:p3", "#32 Herdr task-start")

    result = start_fixture.run(32)

    assert result.task.workstreams["main"].worktree == str(start_fixture.worktree)
    assert result.task.workstreams["main"].branch == "feat/issue-32-herdr-task-start"


def test_legacy_tab_label_is_renamed_without_duplicate_create(start_fixture: StartFixture) -> None:
    start_fixture.write_state_with_ids("w9", "w9:t2", "w9:p3", tab_label="32 Herdr task-start")
    start_fixture.make_managed_tab("w9", "w9:t2", "w9:p3", "32 Herdr task-start")

    result = start_fixture.run(32)

    assert result.tab_id == "w9:t2"
    assert result.task.workstreams["main"].tab_label == "#32 Herdr task-start"
    assert start_fixture.herdr.count_calls("tab", "rename") == 1
    assert start_fixture.herdr.count_calls("tab", "create") == 0


def test_legacy_tab_with_a_different_root_pane_is_not_renamed(start_fixture: StartFixture) -> None:
    start_fixture.write_state_with_ids("w9", "w9:t2", "w9:p3", tab_label="32 Herdr task-start")
    start_fixture.make_managed_tab("w9", "w9:t2", "w9:p4", "32 Herdr task-start")

    result = start_fixture.run(32)

    assert result.tab_id == "w9:t3"
    assert start_fixture.herdr.tabs["w9:t2"].label == "32 Herdr task-start"
    assert start_fixture.herdr.count_calls("tab", "rename") == 0
    assert start_fixture.herdr.count_calls("tab", "create") == 1


def test_legacy_tab_with_multiple_panes_fails_without_rename(
    start_fixture: StartFixture,
) -> None:
    start_fixture.write_state_with_ids("w9", "w9:t2", "w9:p3", tab_label="32 Herdr task-start")
    start_fixture.make_managed_tab("w9", "w9:t2", "w9:p3", "32 Herdr task-start")
    start_fixture.herdr.set_panes("w9:t2", ["w9:p3", "w9:p4"])

    with pytest.raises(LifecycleError, match="exactly one pane"):
        start_fixture.run(32)

    assert start_fixture.herdr.tabs["w9:t2"].label == "32 Herdr task-start"
    assert start_fixture.herdr.count_calls("tab", "rename") == 0


def test_worktree_owned_by_another_issue_is_rejected_before_herdr_mutation(
    start_fixture: StartFixture,
) -> None:
    start_fixture.run(32)
    before_state = start_fixture.state_bytes()
    before_calls = list(start_fixture.herdr.calls)
    start_fixture.runner.respond_to_issue_lookup(
        returncode=0,
        stdout=json.dumps({"title": "Another Herdr task"}),
    )

    with pytest.raises(LifecycleError, match="already registered"):
        start_fixture.run(33)

    assert start_fixture.state_bytes() == before_state
    assert start_fixture.herdr.calls == before_calls


def test_worktree_owned_by_another_workstream_is_rejected_before_herdr_mutation(
    start_fixture: StartFixture,
) -> None:
    start_fixture.run(32)
    current = start_fixture.state().tasks["dodo5522/ai-agent-home#32"]
    current = current.model_copy(
        update={
            "workstreams": {
                **current.workstreams,
                "review": Workstream(worktree=str(start_fixture.worktree)),
            }
        }
    )
    start_fixture.state_path.write_text(
        TaskState(
            version=1,
            tasks={"dodo5522/ai-agent-home#32": current},
        ).to_json(),
        encoding="utf-8",
    )
    before_state = start_fixture.state_bytes()
    before_calls = list(start_fixture.herdr.calls)

    with pytest.raises(LifecycleError, match="already registered"):
        start_fixture.run(32)

    assert start_fixture.state_bytes() == before_state
    assert start_fixture.herdr.calls == before_calls


def test_different_registered_worktree_is_rejected_without_herdr_mutation(
    start_fixture: StartFixture,
) -> None:
    start_fixture.run(32)
    before_state = start_fixture.state_bytes()
    before_calls = list(start_fixture.herdr.calls)
    replacement = start_fixture.use_second_valid_worktree("feat/issue-32-replacement")

    with pytest.raises(LifecycleError, match="different worktree"):
        start_fixture.run(32, replacement)

    assert start_fixture.state_bytes() == before_state
    assert start_fixture.herdr.calls == before_calls


def test_different_branch_is_rejected_without_herdr_mutation(start_fixture: StartFixture) -> None:
    start_fixture.run(32)
    before_state = start_fixture.state_bytes()
    before_calls = list(start_fixture.herdr.calls)
    start_fixture.respond_worktree(start_fixture.worktree, "feat/issue-32-replacement")

    with pytest.raises(LifecycleError, match="different branch"):
        start_fixture.run(32)

    assert start_fixture.state_bytes() == before_state
    assert start_fixture.herdr.calls == before_calls


@pytest.mark.parametrize("invalid", ["primary", "detached", "unmarked"])
def test_invalid_worktree_is_rejected_before_herdr_mutation(
    start_fixture: StartFixture,
    invalid: str,
) -> None:
    before_calls = list(start_fixture.herdr.calls)
    if invalid == "primary":
        start_fixture.respond_worktree(
            start_fixture.worktree,
            "main",
            git_dir=start_fixture.git_common_dir,
        )
    elif invalid == "detached":
        start_fixture.respond_worktree(start_fixture.worktree, None)
    else:
        (start_fixture.task_root / ".codex-task-root").unlink()

    with pytest.raises(LifecycleError):
        start_fixture.run(32)

    assert not start_fixture.state_path.exists()
    assert start_fixture.herdr.calls == before_calls


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

    with pytest.raises(LifecycleError, match="exactly one pane"):
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

    with pytest.raises(LifecycleError, match="HERDR_ENV"):
        start_fixture.run(32)


def test_failed_workspace_create_leaves_state_absent(start_fixture: StartFixture) -> None:
    start_fixture.herdr.fail_create = True

    with pytest.raises(LifecycleError, match="workspace create"):
        start_fixture.run(32)

    assert not start_fixture.state_path.exists()


def test_failed_tab_rename_leaves_state_absent(start_fixture: StartFixture) -> None:
    start_fixture.herdr.fail_rename = True

    with pytest.raises(LifecycleError, match="tab rename"):
        start_fixture.run(32)

    assert not start_fixture.state_path.exists()


def test_failed_state_write_rolls_back_created_workspace(
    start_fixture: StartFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_put(self: StateStore, key: str, task: Task) -> Task:
        raise LifecycleError("state write failed")

    monkeypatch.setattr(StateStore, "put", fail_put)

    with pytest.raises(LifecycleError, match="state write failed"):
        start_fixture.run(32)

    assert not start_fixture.state_path.exists()
    assert start_fixture.herdr.was_called("workspace", "close", "w9")


def test_start_cli_help_describes_issue_and_cwd(capsys: pytest.CaptureFixture[str]) -> None:
    assert lifecycle_main(["start", "--help"]) == 0
    output = capsys.readouterr().out
    assert "ISSUE_NUMBER" in output
    assert "--cwd" in output


def test_start_cli_rejects_invalid_issue(capsys: pytest.CaptureFixture[str]) -> None:
    assert lifecycle_main(["start", "not-a-number"]) == 2
    assert "ISSUE_NUMBER" in capsys.readouterr().err


def test_start_cli_maps_missing_herdr_environment_to_runtime_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("HERDR_ENV", raising=False)

    assert lifecycle_main(["start", "32", "--cwd", str(tmp_path)]) == 1
    assert "HERDR_ENV" in capsys.readouterr().err
