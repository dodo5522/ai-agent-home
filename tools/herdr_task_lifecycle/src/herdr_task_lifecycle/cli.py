"""Command-line interface for the Herdr task lifecycle."""

import argparse
import sys
from collections.abc import Callable, Sequence

from .commands.cleanup.command import add_parser as add_cleanup_parser
from .commands.start.command import add_parser as add_start_parser
from .errors import ExitCode, LifecycleError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="herdr-task",
        description="Manage the Herdr task lifecycle.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    add_start_parser(subparsers)
    add_cleanup_parser(subparsers)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the lifecycle CLI and return its process exit code."""
    try:
        args = _parser().parse_args(argv)
        handler: Callable[[argparse.Namespace], int] = args.handler
        return handler(args)
    except SystemExit as exc:
        return int(exc.code)
    except LifecycleError as exc:
        print(f"herdr-task: {exc}", file=sys.stderr)
        return ExitCode.RUNTIME_ERROR
