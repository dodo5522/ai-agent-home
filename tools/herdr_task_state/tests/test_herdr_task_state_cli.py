import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from herdr_task_state.cli import ExitCode

ROOT = Path(__file__).parents[3]
CLI = ROOT / "bin" / "herdr-task-state"


def test_exit_codes_have_named_meanings() -> None:
    assert ExitCode.SUCCESS == 0
    assert ExitCode.RUNTIME_ERROR == 1
    assert ExitCode.USAGE_ERROR == 2
    assert ExitCode.NOT_FOUND == 3


def test_top_level_help_describes_commands_and_examples(
    invoke: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    result = invoke("--help")

    assert result.returncode == 0
    assert "Manage Herdr task state" in result.stdout
    assert "init" in result.stdout
    assert "validate" in result.stdout
    assert "get" in result.stdout
    assert "put" in result.stdout
    assert "remove" in result.stdout
    assert "Examples:" in result.stdout
    assert result.stderr == ""


def test_subcommand_help_describes_arguments_and_formats(
    invoke: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    get_result = invoke("get", "--help")
    put_result = invoke("put", "--help")

    assert get_result.returncode == 0
    assert "Print one task" in get_result.stdout
    assert "TASK_KEY" in get_result.stdout
    assert "owner/repository#issue-number" in get_result.stdout
    assert put_result.returncode == 0
    assert "Store one validated task" in put_result.stdout
    assert "TASK_KEY" in put_result.stdout
    assert "TASK_JSON_FILE" in put_result.stdout
    assert put_result.stderr == ""


def test_invalid_task_key_is_rejected_by_argparse(
    invoke: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    result = invoke("get", "not-a-task-key")

    assert result.returncode == 2
    assert "argument TASK_KEY" in result.stderr
    assert "task key must be owner/repository#positive-issue-number" in result.stderr
    assert result.stdout == ""


@pytest.fixture
def cli_env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HERDR_TASK_STATE_FILE"] = str(tmp_path / "state.json")
    return env


@pytest.fixture
def invoke(cli_env: dict[str, str]) -> Callable[..., subprocess.CompletedProcess[str]]:
    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([str(CLI), *args], env=cli_env, text=True, capture_output=True)

    return run


@pytest.fixture
def task_file(tmp_path: Path) -> Callable[[int], str]:
    def write(number: int) -> str:
        path = tmp_path / f"task-{number}.json"
        path.write_text(
            json.dumps(
                {
                    "repository": "dodo5522/ai-agent-home",
                    "issue_number": number,
                    "workstreams": {"main": {}},
                }
            ),
            encoding="utf-8",
        )
        return str(path)

    return write


def test_lifecycle_and_statuses(
    invoke: Callable[..., subprocess.CompletedProcess[str]], task_file: Callable[[int], str]
) -> None:
    assert invoke("init").stdout == ""
    assert invoke("get", "dodo5522/ai-agent-home#1").returncode == 3
    result = invoke("put", "dodo5522/ai-agent-home#1", task_file(1))
    assert result.returncode == 0
    assert json.loads(result.stdout)["issue_number"] == 1
    assert invoke("get", "bad-key").returncode == 2
    assert invoke("remove", "dodo5522/ai-agent-home#1").returncode == 0


def test_rejects_trailing_json_and_preserves_state(
    invoke: Callable[..., subprocess.CompletedProcess[str]], cli_env: dict[str, str], tmp_path: Path
) -> None:
    assert invoke("init").returncode == 0
    source = tmp_path / "bad.json"
    source.write_text(
        '{"repository":"dodo5522/ai-agent-home","issue_number":2,"workstreams":{"main":{}}}\n{}',
        encoding="utf-8",
    )
    result = invoke("put", "dodo5522/ai-agent-home#2", str(source))
    assert result.returncode == 2
    assert result.stdout == ""
    assert json.loads(Path(cli_env["HERDR_TASK_STATE_FILE"]).read_text())["tasks"] == {}


def test_concurrent_puts_preserve_every_task(
    invoke: Callable[..., subprocess.CompletedProcess[str]],
    cli_env: dict[str, str],
    task_file: Callable[[int], str],
) -> None:
    assert invoke("init").returncode == 0
    processes = [
        subprocess.Popen(
            [str(CLI), "put", f"dodo5522/ai-agent-home#{n}", task_file(n)],
            env=cli_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for n in range(10, 20)
    ]
    results = [process.communicate(timeout=10) for process in processes]
    assert all(process.returncode == 0 for process in processes), results
    state = json.loads(Path(cli_env["HERDR_TASK_STATE_FILE"]).read_text())
    assert set(state["tasks"]) == {f"dodo5522/ai-agent-home#{n}" for n in range(10, 20)}
