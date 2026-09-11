"""Subprocess boundary used by task-start adapters."""

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .errors import TaskStartError


@dataclass(frozen=True)
class CommandResult:
    """Captured result of one external command invocation."""

    returncode: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    """Interface for running external commands."""

    def run(self, arguments: Sequence[str], cwd: Path | None = None) -> CommandResult:
        """Run one command and capture its result."""


class SubprocessRunner:
    """Run commands through Python's subprocess API without a shell."""

    def run(self, arguments: Sequence[str], cwd: Path | None = None) -> CommandResult:
        """Run one command and capture stdout, stderr, and its exit status."""
        try:
            completed = subprocess.run(
                arguments,
                cwd=cwd,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as error:
            raise TaskStartError(f"cannot execute {arguments[0]}") from error
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)
