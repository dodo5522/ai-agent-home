from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from herdr_runtime import CommandResult

from herdr_task_lifecycle.errors import LifecycleError
from herdr_task_lifecycle.worktree import (
    WorktreeRegistration,
    resolve_managed_worktree,
)


@dataclass
class RecordingRunner:
    responses: dict[tuple[str, ...], CommandResult] = field(default_factory=dict)

    def run(
        self,
        arguments: Sequence[str],
        cwd: Path | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> CommandResult:
        del cwd, environment
        try:
            return self.responses[tuple(arguments)]
        except KeyError as error:
            raise AssertionError(f"unexpected command: {arguments}") from error

    def respond(self, arguments: Sequence[str], result: CommandResult) -> None:
        self.responses[tuple(arguments)] = result


@dataclass
class WorktreeFixture:
    tmp_path: Path
    runner: RecordingRunner
    tasks_directory: Path
    task_root: Path
    worktree: Path
    marker: Path
    git_dir: Path
    git_common_dir: Path
    primary_worktree: Path

    def command(self, *arguments: str) -> list[str]:
        return ["git", "-C", str(self.worktree), *arguments]

    def respond_git_layout(
        self,
        *,
        git_dir: Path | None = None,
        git_common_dir: Path | None = None,
        branch: str | None = "feat/issue-30-herdr-work-management",
        inventory: str | None = None,
    ) -> None:
        resolved_git_dir = git_dir or self.git_dir
        resolved_common_dir = git_common_dir or self.git_common_dir
        self.runner.respond(
            self.command("rev-parse", "--git-dir"),
            CommandResult(0, f"{resolved_git_dir}\n", ""),
        )
        self.runner.respond(
            self.command("rev-parse", "--git-common-dir"),
            CommandResult(0, f"{resolved_common_dir}\n", ""),
        )
        if branch is None:
            self.runner.respond(
                self.command("symbolic-ref", "--quiet", "--short", "HEAD"),
                CommandResult(1, "", "detached HEAD"),
            )
        else:
            self.runner.respond(
                self.command("symbolic-ref", "--quiet", "--short", "HEAD"),
                CommandResult(0, f"{branch}\n", ""),
            )
        self.runner.respond(
            self.command("worktree", "list", "--porcelain"),
            CommandResult(0, inventory or self.inventory(branch or "main"), ""),
        )

    def inventory(self, branch: str) -> str:
        return (
            f"worktree {self.primary_worktree}\n"
            f"HEAD {'0' * 40}\n"
            "branch refs/heads/main\n\n"
            f"worktree {self.worktree}\n"
            f"HEAD {'1' * 40}\n"
            f"branch refs/heads/{branch}\n"
        )


@pytest.fixture
def worktree_fixture(tmp_path: Path) -> WorktreeFixture:
    tasks_directory = tmp_path / "tasks"
    task_root = tasks_directory / "issue-30"
    worktree = task_root / "worktree"
    marker = task_root / ".codex-task-root"
    worktree.mkdir(parents=True)
    marker.touch()
    git_common_dir = tmp_path / "repository" / ".git"
    git_dir = git_common_dir / "worktrees" / "issue-30"
    git_dir.mkdir(parents=True)
    fixture = WorktreeFixture(
        tmp_path=tmp_path,
        runner=RecordingRunner(),
        tasks_directory=tasks_directory,
        task_root=task_root,
        worktree=worktree,
        marker=marker,
        git_dir=git_dir,
        git_common_dir=git_common_dir,
        primary_worktree=tmp_path / "repository",
    )
    fixture.respond_git_layout()
    return fixture


def test_resolves_registered_branch_worktree_under_marker(
    worktree_fixture: WorktreeFixture,
) -> None:
    registration = resolve_managed_worktree(
        worktree_fixture.worktree,
        worktree_fixture.runner,
        worktree_fixture.tasks_directory,
    )

    assert registration == WorktreeRegistration(
        path=worktree_fixture.worktree,
        branch="feat/issue-30-herdr-work-management",
        task_root=worktree_fixture.task_root,
    )


def test_rejects_primary_checkout(worktree_fixture: WorktreeFixture) -> None:
    worktree_fixture.respond_git_layout(
        git_dir=worktree_fixture.git_common_dir,
        git_common_dir=worktree_fixture.git_common_dir,
        branch="main",
    )

    with pytest.raises(LifecycleError, match="primary worktree"):
        resolve_managed_worktree(
            worktree_fixture.worktree,
            worktree_fixture.runner,
            worktree_fixture.tasks_directory,
        )


def test_rejects_detached_head(worktree_fixture: WorktreeFixture) -> None:
    worktree_fixture.respond_git_layout(branch=None)

    with pytest.raises(LifecycleError, match="detached HEAD"):
        resolve_managed_worktree(
            worktree_fixture.worktree,
            worktree_fixture.runner,
            worktree_fixture.tasks_directory,
        )


def test_rejects_missing_inventory_record(worktree_fixture: WorktreeFixture) -> None:
    worktree_fixture.respond_git_layout(
        inventory=(
            f"worktree {worktree_fixture.primary_worktree}\n"
            f"HEAD {'0' * 40}\n"
            "branch refs/heads/main\n"
        )
    )

    with pytest.raises(LifecycleError, match="registered Git worktree"):
        resolve_managed_worktree(
            worktree_fixture.worktree,
            worktree_fixture.runner,
            worktree_fixture.tasks_directory,
        )


def test_rejects_missing_task_root_marker(worktree_fixture: WorktreeFixture) -> None:
    worktree_fixture.marker.unlink()

    with pytest.raises(LifecycleError, match="task root"):
        resolve_managed_worktree(
            worktree_fixture.worktree,
            worktree_fixture.runner,
            worktree_fixture.tasks_directory,
        )


def test_rejects_marker_outside_task_root_boundary(worktree_fixture: WorktreeFixture) -> None:
    outside_root = worktree_fixture.tmp_path / "outside" / "issue-30"
    outside_worktree = outside_root / "worktree"
    outside_worktree.mkdir(parents=True)
    (outside_root / ".codex-task-root").touch()
    worktree_fixture.worktree = outside_worktree
    worktree_fixture.respond_git_layout()

    with pytest.raises(LifecycleError, match="task root"):
        resolve_managed_worktree(
            outside_worktree,
            worktree_fixture.runner,
            worktree_fixture.tasks_directory,
        )


def test_git_failure_does_not_echo_command_output(worktree_fixture: WorktreeFixture) -> None:
    worktree_fixture.runner.respond(
        worktree_fixture.command("rev-parse", "--git-dir"),
        CommandResult(1, "sentinel-secret", "sentinel-secret"),
    )

    with pytest.raises(LifecycleError, match="inspect Git worktree") as error:
        resolve_managed_worktree(
            worktree_fixture.worktree,
            worktree_fixture.runner,
            worktree_fixture.tasks_directory,
        )

    assert "sentinel-secret" not in str(error.value)
