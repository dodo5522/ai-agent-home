"""Command-line entry point for Herdr task startup."""

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from herdr_task_state.cli import ExitCode
from herdr_task_state.model import StateValidationError
from herdr_task_state.store import StateFilesystemError

from herdr_task_start.start import TaskStarter, TaskStartError


def _state_path() -> Path:
    value = os.environ.get("HERDR_TASK_STATE_FILE")
    if value is None:
        value = os.path.join(
            os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")),
            "ai-agent-home",
            "herdr-tasks.json",
        )
    path = Path(value)
    if not path.is_absolute():
        raise TaskStartError(f"state path must be absolute: {path}")
    return path


def _issue_number(value: str) -> int:
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive integer") from error
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def main(argv: Sequence[str] | None = None) -> int:
    """Resolve one Issue's Herdr resources and return its process exit code."""
    parser = argparse.ArgumentParser(
        prog="herdr-task-start",
        description="Create or reuse managed Herdr resources for one GitHub Issue.",
    )
    parser.add_argument(
        "issue_number",
        type=_issue_number,
        metavar="ISSUE_NUMBER",
        help="Positive GitHub Issue number for the current repository.",
    )
    parser.add_argument(
        "--cwd",
        type=Path,
        default=Path.cwd(),
        metavar="PATH",
        help="Repository or Issue-worktree directory (default: current directory).",
    )
    try:
        args = parser.parse_args(argv)
        cwd = args.cwd.expanduser().resolve()
        resolution = TaskStarter(_state_path()).start(args.issue_number, cwd)
        print(resolution.task.to_json())
        return ExitCode.SUCCESS
    except StateValidationError as error:
        print(f"herdr-task-start: {error}", file=sys.stderr)
        return ExitCode.USAGE_ERROR
    except (StateFilesystemError, TaskStartError) as error:
        print(f"herdr-task-start: {error}", file=sys.stderr)
        return ExitCode.RUNTIME_ERROR
