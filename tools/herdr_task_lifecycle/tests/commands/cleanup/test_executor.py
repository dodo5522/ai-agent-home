import json
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from herdr_task_state.model import HerdrReference, Task, TaskKey, TaskState, Workstream
from herdr_task_state.store import StateStore

from herdr_task_lifecycle.cli import main as lifecycle_main
from herdr_task_lifecycle.commands.cleanup.executor import CleanupExecutor, CleanupResult
from herdr_task_lifecycle.commands.cleanup.planner import (
    CleanupActionPlan,
    CleanupPlan,
    CleanupPlanner,
)
from herdr_task_lifecycle.errors import LifecycleError
from herdr_task_lifecycle.herdr import TabInfo, WorkspaceInfo
from herdr_task_lifecycle.runner import CommandResult
from herdr_task_lifecycle.state import TaskStateRepository


@dataclass
class FakeCleanupHerdr:
    events: list[str]
    workspaces: dict[str, WorkspaceInfo]
    tabs: dict[str, TabInfo]
    failure: str | None = None

    def workspace_find(self, workspace_id: str) -> WorkspaceInfo | None:
        return self.workspaces.get(workspace_id)

    def tab_find(self, tab_id: str) -> TabInfo | None:
        return self.tabs.get(tab_id)

    def tab_close(self, tab_id: str) -> None:
        self.events.append("tab")
        if self.failure == "tab":
            raise LifecycleError("injected tab failure")
        self.tabs.pop(tab_id, None)


@dataclass
class FakeCleanupRunner:
    repository_path: Path
    primary_path: Path
    registered_worktrees: set[Path]
    events: list[str]
    failure: str | None = None
    remove_marker_after_worktree: Path | None = None
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
        if command == (
            "git",
            "-C",
            str(self.repository_path),
            "worktree",
            "list",
            "--porcelain",
        ):
            paths = [self.primary_path, *sorted(self.registered_worktrees, key=str)]
            records = [
                f"worktree {path}\nHEAD {'0' * 40}\nbranch refs/heads/test-{index}\n"
                for index, path in enumerate(paths)
            ]
            return CommandResult(0, "\n".join(records), "")
        if command[:5] == (
            "git",
            "-C",
            str(self.repository_path),
            "worktree",
            "remove",
        ):
            self.events.append("worktree")
            if self.failure == "worktree":
                return CommandResult(1, "sensitive stdout", "sensitive stderr")
            target = Path(command[5])
            self.registered_worktrees.remove(target)
            shutil.rmtree(target)
            if self.remove_marker_after_worktree is not None:
                self.remove_marker_after_worktree.unlink()
            return CommandResult(0, "", "")
        raise AssertionError(f"unexpected command: {command}")


class RecordingTaskStateRepository(TaskStateRepository):
    def __init__(self, path: Path, events: list[str]) -> None:
        super().__init__(path)
        self._events = events

    def remove_task_after_cleanup(self, task_key: TaskKey) -> None:
        super().remove_task_after_cleanup(task_key)
        self._events.append("state")


@dataclass
class CleanupFixture:
    tasks_directory: Path
    repository_path: Path
    task_root: Path
    worktree: Path
    state_path: Path
    task_key: TaskKey
    events: list[str]
    runner: FakeCleanupRunner
    herdr: FakeCleanupHerdr

    @property
    def planner(self) -> CleanupPlanner:
        return CleanupPlanner(
            self.state_path,
            self.repository_path,
            runner=self.runner,
            herdr=self.herdr,
            tasks_directory=self.tasks_directory,
        )

    @property
    def executor(self) -> CleanupExecutor:
        def remove_task_root(path: Path) -> None:
            self.events.append("task_root")
            shutil.rmtree(path)

        return CleanupExecutor(
            self.state_path,
            self.repository_path,
            runner=self.runner,
            herdr=self.herdr,
            tasks_directory=self.tasks_directory,
            remove_task_root=remove_task_root,
            state_repository=RecordingTaskStateRepository(self.state_path, self.events),
        )

    def state(self) -> TaskState:
        return StateStore(self.state_path).read()

    def fail_on(self, action: str) -> None:
        self.runner.failure = action
        self.herdr.failure = action

    def clear_failure(self) -> None:
        self.runner.failure = None
        self.herdr.failure = None


@pytest.fixture
def cleanup_fixture(tmp_path: Path) -> CleanupFixture:
    tasks_directory = tmp_path / "home" / "takashi" / "work" / "tasks"
    task_root = tasks_directory / "issue-33"
    worktree = task_root / "worktree"
    repository_path = tmp_path / "repository"
    repository_path.mkdir()
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text("gitdir: test\n", encoding="utf-8")
    (task_root / ".codex-task-root").touch()
    state_path = tmp_path / "state.json"
    task_key = TaskKey("dodo5522/ai-agent-home", 33)
    task = Task(
        repository=task_key.repository,
        issue_number=task_key.issue_number,
        title="Cleanup execution",
        herdr=HerdrReference(workspace_id="w9", workspace_label="dodo5522/ai-agent-home"),
        workstreams={
            "main": Workstream(
                tab_id="w9:t33",
                tab_label="33 Cleanup execution",
                worktree=str(worktree),
            )
        },
    )
    StateStore(state_path).put(str(task_key), task)
    events: list[str] = []
    runner = FakeCleanupRunner(repository_path, repository_path, {worktree}, events)
    herdr = FakeCleanupHerdr(
        events,
        {"w9": WorkspaceInfo("w9", "dodo5522/ai-agent-home")},
        {"w9:t33": TabInfo("w9:t33", "w9", "33 Cleanup execution")},
    )
    return CleanupFixture(
        tasks_directory,
        repository_path,
        task_root,
        worktree,
        state_path,
        task_key,
        events,
        runner,
        herdr,
    )


def test_execute_runs_tab_worktree_root_then_removes_state(
    cleanup_fixture: CleanupFixture,
) -> None:
    plan = cleanup_fixture.planner.plan(cleanup_fixture.task_key)

    result = cleanup_fixture.executor.execute(plan, cleanup_fixture.task_root)

    assert cleanup_fixture.events == ["tab", "worktree", "task_root", "state"]
    assert result.task_key == cleanup_fixture.task_key
    assert result.completed_actions == ("tab", "worktree", "task_root")
    assert result.mapping_removed is True
    assert cleanup_fixture.state().tasks == {}


def test_execute_persists_partial_progress_and_retry_skips_completed_action(
    cleanup_fixture: CleanupFixture,
) -> None:
    cleanup_fixture.fail_on("worktree")

    with pytest.raises(LifecycleError, match="worktree"):
        cleanup_fixture.executor.execute(
            cleanup_fixture.planner.plan(cleanup_fixture.task_key),
            cleanup_fixture.task_root,
        )

    task = cleanup_fixture.state().tasks[str(cleanup_fixture.task_key)]
    assert task.cleanup is not None
    assert task.cleanup.phase == "partial"
    assert task.cleanup.completed_actions == {"tab"}

    cleanup_fixture.clear_failure()
    cleanup_fixture.executor.execute(
        cleanup_fixture.planner.plan(cleanup_fixture.task_key),
        cleanup_fixture.task_root,
    )

    assert cleanup_fixture.events.count("tab") == 1
    assert cleanup_fixture.events == [
        "tab",
        "worktree",
        "worktree",
        "task_root",
        "state",
    ]


def test_execute_refuses_different_confirmed_root(cleanup_fixture: CleanupFixture) -> None:
    with pytest.raises(LifecycleError, match="confirm-task-root"):
        cleanup_fixture.executor.execute(
            cleanup_fixture.planner.plan(cleanup_fixture.task_key), Path("/tmp/other")
        )

    assert cleanup_fixture.events == []
    assert cleanup_fixture.state().tasks[str(cleanup_fixture.task_key)].cleanup is None


def test_execute_revalidates_before_each_action_and_preserves_mapping(
    cleanup_fixture: CleanupFixture,
) -> None:
    plan = cleanup_fixture.planner.plan(cleanup_fixture.task_key)
    marker = cleanup_fixture.task_root / ".codex-task-root"
    cleanup_fixture.runner.remove_marker_after_worktree = marker

    with pytest.raises(LifecycleError, match="task_root"):
        cleanup_fixture.executor.execute(plan, cleanup_fixture.task_root)

    assert cleanup_fixture.events == ["tab", "worktree"]
    task = cleanup_fixture.state().tasks[str(cleanup_fixture.task_key)]
    assert task.cleanup is not None
    assert task.cleanup.phase == "partial"
    assert task.cleanup.completed_actions == {"tab", "worktree"}
    assert cleanup_fixture.task_root.exists()


def test_execute_skips_validated_actions_that_are_already_absent(
    cleanup_fixture: CleanupFixture,
) -> None:
    cleanup_fixture.herdr.tabs.clear()
    cleanup_fixture.runner.registered_worktrees.clear()
    shutil.rmtree(cleanup_fixture.worktree)

    result = cleanup_fixture.executor.execute(
        cleanup_fixture.planner.plan(cleanup_fixture.task_key), cleanup_fixture.task_root
    )

    assert cleanup_fixture.events == ["task_root", "state"]
    assert result.completed_actions == ("tab", "worktree", "task_root")


def test_cleanup_execute_uses_resolved_confirmation_and_emits_result_json(
    cleanup_fixture: CleanupFixture,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from herdr_task_lifecycle.commands.cleanup import command

    plan = CleanupPlan(
        cleanup_fixture.task_key,
        cleanup_fixture.task_root,
        (
            CleanupActionPlan("tab", "delete", "w9:t33", "validated"),
            CleanupActionPlan("worktree", "delete", str(cleanup_fixture.worktree), "validated"),
            CleanupActionPlan("task_root", "delete", str(cleanup_fixture.task_root), "validated"),
        ),
    )
    received: list[Path] = []

    class StubPlanner:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def plan(self, task_key: TaskKey) -> CleanupPlan:
            assert task_key == cleanup_fixture.task_key
            return plan

    class StubExecutor:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def execute(self, selected: CleanupPlan, confirmed: Path) -> CleanupResult:
            assert selected is plan
            received.append(confirmed)
            return CleanupResult(
                cleanup_fixture.task_key,
                ("tab", "worktree", "task_root"),
                mapping_removed=True,
            )

    monkeypatch.chdir(cleanup_fixture.repository_path)
    monkeypatch.setattr(command, "resolve_repository", lambda cwd, runner: "dodo5522/ai-agent-home")
    monkeypatch.setattr(command, "state_path", lambda: cleanup_fixture.state_path)
    monkeypatch.setattr(command, "CleanupPlanner", StubPlanner)
    monkeypatch.setattr(command, "CleanupExecutor", StubExecutor)

    assert (
        lifecycle_main(
            [
                "cleanup",
                "33",
                "--execute",
                "--confirm-task-root",
                str(cleanup_fixture.task_root.parent / "." / cleanup_fixture.task_root.name),
            ]
        )
        == 0
    )
    assert received == [cleanup_fixture.task_root.resolve()]
    assert json.loads(capsys.readouterr().out) == {
        "completed_actions": ["tab", "worktree", "task_root"],
        "mapping_removed": True,
        "task_key": "dodo5522/ai-agent-home#33",
    }
