"""Validation for managed Git worktrees used by Issue tasks."""

from dataclasses import dataclass
from pathlib import Path

from .errors import LifecycleError
from .runner import CommandResult, CommandRunner

TASK_ROOTS_DIRECTORY = Path("/home/takashi/work/tasks")


@dataclass(frozen=True)
class WorktreeRegistration:
    """Validated Git and task-root references for one worktree."""

    path: Path
    branch: str
    task_root: Path


def _git_result(runner: CommandRunner, arguments: list[str]) -> CommandResult:
    result = runner.run(arguments)
    if result.returncode != 0:
        raise LifecycleError("cannot inspect Git worktree")
    return result


def _git_path(cwd: Path, result: CommandResult) -> Path:
    value = result.stdout.strip()
    if not value:
        raise LifecycleError("cannot inspect Git worktree")
    path = Path(value)
    return (path if path.is_absolute() else cwd / path).resolve()


def _inventory_paths(result: CommandResult) -> set[Path]:
    paths: set[Path] = set()
    for record in result.stdout.split("\n\n"):
        for line in record.splitlines():
            if line.startswith("worktree "):
                paths.add(Path(line.removeprefix("worktree ")).resolve())
    return paths


def _task_root(cwd: Path, task_roots_directory: Path) -> Path:
    boundary = task_roots_directory.resolve()
    for candidate in (cwd, *cwd.parents):
        marker = candidate / ".codex-task-root"
        if marker.is_file() and not marker.is_symlink():
            if candidate == boundary or not candidate.is_relative_to(boundary):
                raise LifecycleError("task root is outside the managed tasks directory")
            return candidate
    raise LifecycleError("cannot find a marked task root")


def resolve_managed_worktree(
    cwd: Path,
    runner: CommandRunner,
    task_roots_directory: Path = TASK_ROOTS_DIRECTORY,
) -> WorktreeRegistration:
    """Return one branch-attached non-primary worktree beneath a task root."""
    path = cwd.resolve()
    if not path.is_absolute() or not path.is_dir():
        raise LifecycleError("cwd must be an absolute directory")

    git_dir = _git_path(
        path,
        _git_result(runner, ["git", "-C", str(path), "rev-parse", "--git-dir"]),
    )
    git_common_dir = _git_path(
        path,
        _git_result(runner, ["git", "-C", str(path), "rev-parse", "--git-common-dir"]),
    )
    if git_dir == git_common_dir:
        raise LifecycleError("cwd is the primary worktree")

    symbolic_ref = runner.run(
        ["git", "-C", str(path), "symbolic-ref", "--quiet", "--short", "HEAD"]
    )
    if symbolic_ref.returncode != 0:
        raise LifecycleError("cwd has detached HEAD")
    branch = symbolic_ref.stdout.strip()
    if not branch:
        raise LifecycleError("cwd has no local branch")

    inventory = _git_result(
        runner,
        ["git", "-C", str(path), "worktree", "list", "--porcelain"],
    )
    if path not in _inventory_paths(inventory):
        raise LifecycleError("cwd is not a registered Git worktree")

    return WorktreeRegistration(
        path=path, branch=branch, task_root=_task_root(path, task_roots_directory)
    )
