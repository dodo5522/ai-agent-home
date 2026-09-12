"""Command-line interface for the Herdr task lifecycle."""

import argparse
import sys
from collections.abc import Callable, Sequence

from .errors import ExitCode, LifecycleError


def _unavailable_command(_: argparse.Namespace) -> int:
    """Report a lifecycle operation that a later package will implement."""
    raise LifecycleError("this lifecycle command is not available yet")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="herdr-task",
        description="Manage the Herdr task lifecycle.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("start", "cleanup"):
        command = subparsers.add_parser(name, help=f"{name.capitalize()} a Herdr task.")
        command.set_defaults(handler=_unavailable_command)
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
