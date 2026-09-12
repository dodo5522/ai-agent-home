"""CLI wiring for read-only cleanup plans and guarded future execution."""

import argparse
from pathlib import Path

from herdr_task_state.model import TaskKey

from ...errors import ExitCode, LifecycleError
from ...identity import resolve_repository
from ...runner import SubprocessRunner
from ...state import state_path
from .planner import CleanupPlanner


def _issue_number(value: str) -> int:
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive integer") from error
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def _absolute_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise argparse.ArgumentTypeError("must be an absolute path")
    return path.resolve(strict=False)


def _run(args: argparse.Namespace) -> int:
    parser: argparse.ArgumentParser = args.command_parser
    if args.execute:
        if args.confirm_task_root is None:
            parser.error("--execute requires --confirm-task-root")
        raise LifecycleError("cleanup execution is not available until the executor is installed")
    if args.confirm_task_root is not None:
        parser.error("--confirm-task-root requires --execute")

    cwd = Path.cwd().resolve()
    runner = SubprocessRunner()
    repository = resolve_repository(cwd, runner)
    task_key = TaskKey(repository, args.issue_number)
    plan = CleanupPlanner(state_path(), cwd, runner=runner).plan(task_key)
    print(plan.to_json())
    return ExitCode.SUCCESS


def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register cleanup plan and guarded execution modes."""
    parser = subparsers.add_parser(
        "cleanup",
        help="Cleanup a Herdr task.",
        description="Plan or execute cleanup for one GitHub Issue task.",
    )
    parser.add_argument(
        "issue_number",
        type=_issue_number,
        metavar="ISSUE",
        help="Positive GitHub Issue number for the current repository.",
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--plan", action="store_true", help="Print a read-only cleanup plan.")
    modes.add_argument("--execute", action="store_true", help="Execute an approved cleanup plan.")
    parser.add_argument(
        "--confirm-task-root",
        type=_absolute_path,
        metavar="PATH",
        help="Exact absolute task-root path from an approved plan.",
    )
    parser.set_defaults(handler=_run, command_parser=parser)
