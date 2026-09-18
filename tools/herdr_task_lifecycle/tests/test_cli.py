"""Tests for the public lifecycle command-line interface."""

import pytest

from herdr_task_lifecycle.cli import main


def test_root_help_lists_start_and_cleanup(capsys: pytest.CaptureFixture[str]) -> None:
    """The command discovers both lifecycle operations from its root help."""
    assert main(["--help"]) == 0
    output = capsys.readouterr().out
    assert "start" in output
    assert "cleanup" in output


def test_unknown_subcommand_is_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    """An unknown root command returns the conventional usage exit code."""
    assert main(["unknown"]) == 2
    assert "invalid choice" in capsys.readouterr().err


def test_start_help_exposes_issue_and_cwd(capsys: pytest.CaptureFixture[str]) -> None:
    """The root parser delegates start parsing to its command package."""
    assert main(["start", "--help"]) == 0
    output = capsys.readouterr().out
    assert "ISSUE_NUMBER" in output
    assert "--cwd" in output
