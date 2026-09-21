"""CLI wiring for the Herdr task start command."""

import argparse
from pathlib import Path

from ...errors import ExitCode
from ...herdr import HerdrClient
from ...runner import SubprocessRunner
from ...state import state_path
from .agent import TaskAgentStarter
from .service import TaskStarter


def _issue_number(value: str) -> int:
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive integer") from error
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def _run(args: argparse.Namespace) -> int:
    cwd = args.cwd.expanduser().resolve()
    runner = SubprocessRunner()
    herdr = HerdrClient(runner)
    resolution = TaskStarter(
        state_path(),
        runner=runner,
        herdr=herdr,
        agent_starter=TaskAgentStarter(herdr),
    ).start(args.issue_number, cwd)
    print(resolution.task.to_json())
    return ExitCode.SUCCESS


def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the start operation on the lifecycle root parser."""
    parser = subparsers.add_parser(
        "start",
        help="Start a Herdr task.",
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
    parser.set_defaults(handler=_run)
