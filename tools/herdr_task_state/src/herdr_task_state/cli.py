"""Command-line interface for Herdr task state."""

import argparse
import os
import stat
import sys
from collections.abc import Sequence
from enum import IntEnum
from pathlib import Path

from .model import Model, StateValidationError, Task, TaskKey
from .store import StateFilesystemError, StateStore


class ExitCode(IntEnum):
    """Stable process exit statuses exposed by the task-state CLI."""

    SUCCESS = 0
    RUNTIME_ERROR = 1
    USAGE_ERROR = 2
    NOT_FOUND = 3


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
        raise StateFilesystemError(f"state path must be absolute: {path}")
    return path


def _json(value: Model) -> None:
    print(value.to_json())


def _task_key_argument(value: str) -> str:
    try:
        TaskKey.parse(value)
    except StateValidationError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return value


def _read_task_file(path: Path, key: str) -> Task:
    if path == Path("-"):
        raise StateValidationError("task input must be a regular file")
    source = path
    try:
        st = source.stat()
    except OSError as exc:
        raise StateValidationError("task input must be a readable regular file") from exc
    if not stat.S_ISREG(st.st_mode) or not os.access(source, os.R_OK):
        raise StateValidationError("task input must be a readable regular file")
    try:
        with source.open("r", encoding="utf-8") as stream:
            document = Task.parse(key, stream.read())
    except (OSError, UnicodeError) as exc:
        raise StateValidationError("task input must be a readable regular file") from exc
    return document


def main(argv: Sequence[str] | None = None) -> int:
    """Run the task-state CLI and return its process exit code."""
    os.umask(0o077)
    parser = argparse.ArgumentParser(
        prog="herdr-task-state",
        description="Manage Herdr task state in a validated JSON document.",
        epilog=(
            "Examples:\n"
            "  herdr-task-state init\n"
            "  herdr-task-state put dodo5522/ai-agent-home#30 task.json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser(
        "init",
        help="Create an empty task-state file.",
        description="Create an empty task-state file if it does not exist.",
    )
    init.set_defaults(command="init")
    validate = sub.add_parser(
        "validate",
        help="Validate and print the complete task state.",
        description="Validate and print the complete task-state JSON document.",
    )
    validate.set_defaults(command="validate")
    get = sub.add_parser(
        "get",
        help="Print one task by its stable task key.",
        description="Print one task identified by its stable owner/repository#issue-number key.",
    )
    get.add_argument(
        "task_key",
        type=_task_key_argument,
        metavar="TASK_KEY",
        help="Stable task key in owner/repository#issue-number format.",
    )
    put = sub.add_parser(
        "put",
        help="Store one validated task.",
        description="Store one validated task JSON document atomically.",
    )
    put.add_argument(
        "task_key",
        type=_task_key_argument,
        metavar="TASK_KEY",
        help="Stable task key in owner/repository#issue-number format.",
    )
    put.add_argument(
        "task_file",
        type=Path,
        metavar="TASK_JSON_FILE",
        help="Path to a JSON file containing one task object.",
    )
    remove = sub.add_parser(
        "remove",
        help="Remove one task by its stable task key.",
        description="Remove one task identified by its stable owner/repository#issue-number key.",
    )
    remove.add_argument(
        "task_key",
        type=_task_key_argument,
        metavar="TASK_KEY",
        help="Stable task key in owner/repository#issue-number format.",
    )
    try:
        args = parser.parse_args(argv)
        store = StateStore(_state_path())
        if args.command == "init":
            store.init()
            return ExitCode.SUCCESS
        if args.command == "validate":
            _json(store.read())
            return ExitCode.SUCCESS
        if args.command == "get":
            _json(store.get(args.task_key))
            return ExitCode.SUCCESS
        if args.command == "put":
            _json(store.put(args.task_key, _read_task_file(args.task_file, args.task_key)))
            return ExitCode.SUCCESS
        if args.command == "remove":
            _json(store.remove(args.task_key))
            return ExitCode.SUCCESS
        return ExitCode.USAGE_ERROR
    except KeyError:
        return ExitCode.NOT_FOUND
    except (StateValidationError, argparse.ArgumentError) as exc:
        print(f"herdr-task-state: {exc}", file=sys.stderr)
        return ExitCode.USAGE_ERROR
    except StateFilesystemError as exc:
        print(f"herdr-task-state: {exc}", file=sys.stderr)
        return ExitCode.RUNTIME_ERROR
    except Exception as exc:
        print(f"herdr-task-state: unexpected failure: {exc}", file=sys.stderr)
        return ExitCode.RUNTIME_ERROR
