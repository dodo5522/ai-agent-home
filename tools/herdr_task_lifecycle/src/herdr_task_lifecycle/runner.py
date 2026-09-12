"""Subprocess boundary used by lifecycle adapters."""

import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .errors import LifecycleError


@dataclass(frozen=True)
class CommandResult:
    """Captured result of one external command invocation."""

    returncode: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    """Interface for running external commands."""

    def run(
        self,
        arguments: Sequence[str],
        cwd: Path | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> CommandResult:
        """Run one command and capture its result."""


class SubprocessRunner:
    """Run commands through Python's subprocess API without a shell."""

    def run(
        self,
        arguments: Sequence[str],
        cwd: Path | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> CommandResult:
        """Run one command with optional environment and capture its result."""
        try:
            completed = subprocess.run(
                arguments,
                cwd=cwd,
                capture_output=True,
                text=True,
                check=False,
                env=environment,
            )
        except OSError as error:
            raise LifecycleError(f"cannot execute {arguments[0]}") from error
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)
