import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import FrozenInstanceError, dataclass, field
from pathlib import Path

import pytest
from herdr_task_state.model import HerdrReference, Task, TaskKey, Workstream
from herdr_task_state.store import StateStore

from herdr_task_lifecycle.cli import main as lifecycle_main
from herdr_task_lifecycle.commands.cleanup.planner import CleanupPlanner
from herdr_task_lifecycle.errors import LifecycleError
from herdr_task_lifecycle.herdr import HerdrClient, TabInfo, WorkspaceInfo
from herdr_task_lifecycle.runner import CommandResult


@dataclass
class RecordingRunner:
    result: CommandResult
    calls: list[tuple[str, ...]] = field(default_factory=list)

    def run(
        self,
        arguments: Sequence[str],
        cwd: Path | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> CommandResult:
        del cwd, environment
        self.calls.append(tuple(arguments))
        return self.result


@dataclass
class FakePlanningHerdr:
    workspaces: dict[str, WorkspaceInfo] = field(default_factory=dict)
    tabs: dict[str, TabInfo] = field(default_factory=dict)
    lookup_calls: list[tuple[str, str]] = field(default_factory=list)
    close_calls: list[str] = field(default_factory=list)

    def workspace_find(self, workspace_id: str) -> WorkspaceInfo | None:
        self.lookup_calls.append(("workspace", workspace_id))
        return self.workspaces.get(workspace_id)

    def tab_find(self, tab_id: str) -> TabInfo | None:
        self.lookup_calls.append(("tab", tab_id))
        return self.tabs.get(tab_id)

    def add_tab_with_matching_label(self) -> None:
        self.tabs["w9:t-unmanaged"] = TabInfo("w9:t-unmanaged", "w9", "33 Cleanup planning")


def _porcelain(*paths: Path) -> str:
    records = []
    for index, path in enumerate(paths):
        branch = "main" if index == 0 else f"test-{index}"
        records.append(f"worktree {path}\nHEAD {'0' * 40}\nbranch refs/heads/{branch}\n")
    return "\n".join(records)


@dataclass
class CleanupFixture:
    tmp_path: Path
    tasks_directory: Path
    repository_path: Path
    task_root: Path
    worktree: Path
    state_path: Path
    task_key: TaskKey
    runner: RecordingRunner
    herdr: FakePlanningHerdr

    @property
    def planner(self) -> CleanupPlanner:
        return CleanupPlanner(
            self.state_path,
            self.repository_path,
            runner=self.runner,
            herdr=self.herdr,
            tasks_directory=self.tasks_directory,
        )

    def state(self) -> Task:
        return StateStore(self.state_path).get(str(self.task_key))

    def store(self, task: Task) -> None:
        StateStore(self.state_path).put(str(self.task_key), task)

    def set_task_root(self, task_root: Path) -> None:
        task_root.mkdir(parents=True, exist_ok=True)
        (task_root / ".codex-task-root").touch()
        worktree = task_root / "worktree"
        worktree.mkdir(exist_ok=True)
        task = self.state()
        main = task.workstreams["main"].model_copy(update={"worktree": str(worktree)})
        self.store(task.model_copy(update={"workstreams": {"main": main}}))
        self.task_root = task_root
        self.worktree = worktree
        self.runner.result = CommandResult(0, _porcelain(self.repository_path, self.worktree), "")

    def remove_stored_tab_id(self) -> None:
        task = self.state()
        main = Workstream(
            tab_label=task.workstreams["main"].tab_label,
            worktree=task.workstreams["main"].worktree,
        )
        self.store(task.model_copy(update={"workstreams": {"main": main}}))


@pytest.fixture
def cleanup_fixture(tmp_path: Path) -> CleanupFixture:
    tasks_directory = tmp_path / "home" / "takashi" / "work" / "tasks"
    task_root = tasks_directory / "issue-33"
    worktree = task_root / "worktree"
    repository_path = tmp_path / "repository"
    repository_path.mkdir()
    worktree.mkdir(parents=True)
    (task_root / ".codex-task-root").touch()
    state_path = tmp_path / "state.json"
    task_key = TaskKey("dodo5522/ai-agent-home", 33)
    task = Task(
        repository=task_key.repository,
        issue_number=task_key.issue_number,
        title="Cleanup planning",
        herdr=HerdrReference(workspace_id="w9", workspace_label="dodo5522/ai-agent-home"),
        workstreams={
            "main": Workstream(
                tab_id="w9:t33",
                tab_label="33 Cleanup planning",
                worktree=str(worktree),
            )
        },
    )
    StateStore(state_path).put(str(task_key), task)
    runner = RecordingRunner(CommandResult(0, _porcelain(repository_path, worktree), ""))
    herdr = FakePlanningHerdr(
        workspaces={"w9": WorkspaceInfo("w9", "dodo5522/ai-agent-home")},
        tabs={"w9:t33": TabInfo("w9:t33", "w9", "33 Cleanup planning")},
    )
    return CleanupFixture(
        tmp_path,
        tasks_directory,
        repository_path,
        task_root,
        worktree,
        state_path,
        task_key,
        runner,
        herdr,
    )


def test_plan_only_targets_stored_managed_resources(cleanup_fixture: CleanupFixture) -> None:
    state_before = cleanup_fixture.state_path.read_bytes()

    plan = cleanup_fixture.planner.plan(cleanup_fixture.task_key)

    assert [item.action for item in plan.actions] == ["tab", "worktree", "task_root"]
    assert {item.outcome for item in plan.actions} == {"delete"}
    assert [item.target for item in plan.actions] == [
        "w9:t33",
        str(cleanup_fixture.worktree),
        str(cleanup_fixture.task_root),
    ]
    assert cleanup_fixture.herdr.close_calls == []
    assert cleanup_fixture.state_path.read_bytes() == state_before
    assert cleanup_fixture.runner.calls == [
        (
            "git",
            "-C",
            str(cleanup_fixture.repository_path),
            "worktree",
            "list",
            "--porcelain",
        )
    ]


def test_herdr_cleanup_lookup_uses_exact_stored_ids() -> None:
    workspace_runner = RecordingRunner(
        CommandResult(
            0,
            json.dumps(
                {
                    "result": {
                        "workspaces": [
                            {"workspace_id": "w8", "label": "matching label"},
                            {"workspace_id": "w9", "label": "stored workspace"},
                        ]
                    }
                }
            ),
            "",
        )
    )
    tab_runner = RecordingRunner(
        CommandResult(
            0,
            json.dumps(
                {
                    "result": {
                        "tabs": [
                            {
                                "tab_id": "w9:t32",
                                "workspace_id": "w9",
                                "label": "matching label",
                            },
                            {
                                "tab_id": "w9:t33",
                                "workspace_id": "w9",
                                "label": "stored tab",
                            },
                        ]
                    }
                }
            ),
            "",
        )
    )

    assert HerdrClient(workspace_runner).workspace_find("w9") == WorkspaceInfo(
        "w9", "stored workspace"
    )
    assert HerdrClient(tab_runner).tab_find("w9:t33") == TabInfo("w9:t33", "w9", "stored tab")
    assert workspace_runner.calls == [("herdr", "workspace", "list")]
    assert tab_runner.calls == [("herdr", "tab", "list")]


def test_herdr_cleanup_lookup_reports_absent_exact_id() -> None:
    runner = RecordingRunner(CommandResult(0, json.dumps({"result": {"workspaces": []}}), ""))

    assert HerdrClient(runner).workspace_find("w9") is None


def test_plan_blocks_task_root_outside_tasks_directory(
    cleanup_fixture: CleanupFixture,
) -> None:
    cleanup_fixture.set_task_root(cleanup_fixture.tmp_path / "outside" / "issue-33")

    plan = cleanup_fixture.planner.plan(cleanup_fixture.task_key)

    assert plan.actions[-1].outcome == "blocked"
    assert "outside" in plan.actions[-1].reason


def test_plan_does_not_import_label_matched_unmanaged_tab(
    cleanup_fixture: CleanupFixture,
) -> None:
    cleanup_fixture.remove_stored_tab_id()
    cleanup_fixture.herdr.add_tab_with_matching_label()

    action = cleanup_fixture.planner.plan(cleanup_fixture.task_key).actions[0]

    assert action.outcome == "blocked"
    assert action.target == ""
    assert cleanup_fixture.herdr.lookup_calls == []


def test_plan_reports_missing_stored_tab_as_already_absent(
    cleanup_fixture: CleanupFixture,
) -> None:
    cleanup_fixture.herdr.tabs.clear()

    action = cleanup_fixture.planner.plan(cleanup_fixture.task_key).actions[0]

    assert action.outcome == "already_absent"
    assert action.target == "w9:t33"


def test_plan_blocks_live_stored_tab_when_workspace_is_missing(
    cleanup_fixture: CleanupFixture,
) -> None:
    cleanup_fixture.herdr.workspaces.clear()

    action = cleanup_fixture.planner.plan(cleanup_fixture.task_key).actions[0]

    assert action.outcome == "blocked"
    assert "Tab remains live" in action.reason
    assert cleanup_fixture.herdr.lookup_calls == [
        ("workspace", "w9"),
        ("tab", "w9:t33"),
    ]


@pytest.mark.parametrize(
    ("workspace", "tab", "reason"),
    [
        (
            WorkspaceInfo("w9", "somebody/else"),
            TabInfo("w9:t33", "w9", "33 Cleanup planning"),
            "workspace label",
        ),
        (
            WorkspaceInfo("w9", "dodo5522/ai-agent-home"),
            TabInfo("w9:t33", "other", "33 Cleanup planning"),
            "workspace",
        ),
        (
            WorkspaceInfo("w9", "dodo5522/ai-agent-home"),
            TabInfo("w9:t33", "w9", "different label"),
            "tab label",
        ),
    ],
)
def test_plan_blocks_live_herdr_identity_mismatch(
    cleanup_fixture: CleanupFixture,
    workspace: WorkspaceInfo,
    tab: TabInfo,
    reason: str,
) -> None:
    cleanup_fixture.herdr.workspaces["w9"] = workspace
    cleanup_fixture.herdr.tabs["w9:t33"] = tab

    action = cleanup_fixture.planner.plan(cleanup_fixture.task_key).actions[0]

    assert action.outcome == "blocked"
    assert reason in action.reason


def test_plan_reports_absent_unregistered_worktree_as_already_absent(
    cleanup_fixture: CleanupFixture,
) -> None:
    missing = cleanup_fixture.task_root / "missing-worktree"
    task = cleanup_fixture.state()
    main = task.workstreams["main"].model_copy(update={"worktree": str(missing)})
    cleanup_fixture.store(task.model_copy(update={"workstreams": {"main": main}}))
    cleanup_fixture.runner.result = CommandResult(
        0, _porcelain(cleanup_fixture.repository_path), ""
    )

    action = cleanup_fixture.planner.plan(cleanup_fixture.task_key).actions[1]

    assert action.outcome == "already_absent"
    assert action.target == str(missing)


def test_plan_blocks_existing_unregistered_worktree(cleanup_fixture: CleanupFixture) -> None:
    cleanup_fixture.runner.result = CommandResult(
        0, _porcelain(cleanup_fixture.repository_path), ""
    )

    action = cleanup_fixture.planner.plan(cleanup_fixture.task_key).actions[1]

    assert action.outcome == "blocked"
    assert "not registered" in action.reason


def test_plan_blocks_primary_worktree(cleanup_fixture: CleanupFixture) -> None:
    task = cleanup_fixture.state()
    main = task.workstreams["main"].model_copy(
        update={"worktree": str(cleanup_fixture.repository_path)}
    )
    cleanup_fixture.store(task.model_copy(update={"workstreams": {"main": main}}))

    action = cleanup_fixture.planner.plan(cleanup_fixture.task_key).actions[1]

    assert action.outcome == "blocked"
    assert "primary" in action.reason


def test_plan_blocks_task_root_with_an_unmanaged_registered_worktree(
    cleanup_fixture: CleanupFixture,
) -> None:
    unmanaged = cleanup_fixture.task_root / "unmanaged-worktree"
    unmanaged.mkdir()
    cleanup_fixture.runner.result = CommandResult(
        0,
        _porcelain(
            cleanup_fixture.repository_path,
            cleanup_fixture.worktree,
            unmanaged,
        ),
        "",
    )

    action = cleanup_fixture.planner.plan(cleanup_fixture.task_key).actions[2]

    assert action.outcome == "blocked"
    assert "other registered worktree" in action.reason


def test_plan_blocks_task_root_with_a_foreign_git_worktree(
    cleanup_fixture: CleanupFixture,
) -> None:
    foreign = cleanup_fixture.task_root / "foreign-worktree"
    foreign.mkdir()
    (foreign / ".git").write_text("gitdir: /tmp/foreign/worktrees/task\n", encoding="utf-8")

    action = cleanup_fixture.planner.plan(cleanup_fixture.task_key).actions[2]

    assert action.outcome == "blocked"
    assert "unmanaged Git worktree" in action.reason


def test_plan_blocks_nested_git_marker_inside_stored_worktree(
    cleanup_fixture: CleanupFixture,
) -> None:
    (cleanup_fixture.worktree / ".git").write_text(
        "gitdir: /tmp/managed/worktrees/task\n", encoding="utf-8"
    )
    nested = cleanup_fixture.worktree / "nested-worktree"
    nested.mkdir()
    (nested / ".git").write_text("gitdir: /tmp/foreign/worktrees/task\n", encoding="utf-8")

    action = cleanup_fixture.planner.plan(cleanup_fixture.task_key).actions[2]

    assert action.outcome == "blocked"
    assert "unmanaged Git worktree" in action.reason


def test_plan_blocks_when_task_root_traversal_fails(
    cleanup_fixture: CleanupFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unreadable = cleanup_fixture.task_root / "unreadable"
    unreadable.mkdir()
    real_scandir = os.scandir

    def failing_scandir(path: str | bytes | int | Path) -> os.ScandirIterator[str]:
        if Path(path) == unreadable:
            raise PermissionError("test traversal denial")
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", failing_scandir)

    action = cleanup_fixture.planner.plan(cleanup_fixture.task_key).actions[2]

    assert action.outcome == "blocked"
    assert "could not be scanned" in action.reason


def test_plan_requires_a_task_root_marker_for_every_stored_worktree(
    cleanup_fixture: CleanupFixture,
) -> None:
    unmarked_worktree = cleanup_fixture.tmp_path / "unmarked" / "worktree"
    unmarked_worktree.mkdir(parents=True)
    task = cleanup_fixture.state()
    review = Workstream(
        tab_id="w9:t-review",
        tab_label="33 review",
        worktree=str(unmarked_worktree),
    )
    cleanup_fixture.store(
        task.model_copy(update={"workstreams": {**task.workstreams, "review": review}})
    )
    cleanup_fixture.herdr.tabs["w9:t-review"] = TabInfo("w9:t-review", "w9", "33 review")
    cleanup_fixture.runner.result = CommandResult(
        0,
        _porcelain(
            cleanup_fixture.repository_path,
            cleanup_fixture.worktree,
            unmarked_worktree,
        ),
        "",
    )

    action = cleanup_fixture.planner.plan(cleanup_fixture.task_key).actions[2]

    assert action.outcome == "blocked"
    assert "every stored worktree" in action.reason


def test_plan_blocks_worktree_and_root_when_git_inventory_fails(
    cleanup_fixture: CleanupFixture,
) -> None:
    cleanup_fixture.runner.result = CommandResult(1, "", "fatal: not a repository")

    plan = cleanup_fixture.planner.plan(cleanup_fixture.task_key)

    assert plan.actions[1].outcome == "blocked"
    assert plan.actions[2].outcome == "blocked"
    assert "Git worktree inventory" in plan.actions[1].reason


def test_plan_models_are_immutable_and_emit_normalized_json(
    cleanup_fixture: CleanupFixture,
) -> None:
    plan = cleanup_fixture.planner.plan(cleanup_fixture.task_key)

    with pytest.raises(FrozenInstanceError):
        plan.task_root = None  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        plan.actions[0].outcome = "blocked"  # type: ignore[misc]
    assert json.loads(plan.to_json()) == {
        "actions": [
            {
                "action": "tab",
                "outcome": "delete",
                "reason": "stored Tab matches its live workspace and label",
                "target": "w9:t33",
            },
            {
                "action": "worktree",
                "outcome": "delete",
                "reason": "stored path is a registered non-primary worktree",
                "target": str(cleanup_fixture.worktree),
            },
            {
                "action": "task_root",
                "outcome": "delete",
                "reason": "task root is marked, contained, and has no unmanaged worktrees",
                "target": str(cleanup_fixture.task_root),
            },
        ],
        "task_key": "dodo5522/ai-agent-home#33",
        "task_root": str(cleanup_fixture.task_root),
    }


def test_cleanup_rejects_both_modes_as_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert lifecycle_main(["cleanup", "33", "--plan", "--execute"]) == 2
    assert "not allowed with argument" in capsys.readouterr().err


def test_cleanup_execute_requires_absolute_confirmation(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert lifecycle_main(["cleanup", "33", "--execute"]) == 2
    assert "--confirm-task-root" in capsys.readouterr().err
    assert (
        lifecycle_main(["cleanup", "33", "--execute", "--confirm-task-root", "relative/root"]) == 2
    )
    assert "absolute" in capsys.readouterr().err


def test_planner_rejects_missing_task(cleanup_fixture: CleanupFixture) -> None:
    with pytest.raises(LifecycleError, match="task is not present"):
        cleanup_fixture.planner.plan(TaskKey("dodo5522/ai-agent-home", 34))
