"""Opt-in isolated Herdr session restart coverage."""

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("HERDR_INTEGRATION") != "1",
    reason="set HERDR_INTEGRATION=1 to run isolated Herdr restart coverage",
)


def run(arguments: list[str], environment: dict[str, str]) -> dict[str, object]:
    """Run a Herdr JSON command and require success without exposing output."""
    completed = subprocess.run(
        arguments, capture_output=True, text=True, check=False, env=environment
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def start_server(session: str, environment: dict[str, str]) -> subprocess.Popen[str]:
    """Attach a disposable client until its detached named server is available."""
    client = subprocess.Popen(
        ["script", "-q", "-c", f"herdr session attach {session}", "/dev/null"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        env=environment,
    )
    for _ in range(30):
        status = subprocess.run(
            ["herdr", "--session", session, "status", "--json"],
            capture_output=True,
            text=True,
            check=False,
            env=environment,
        )
        if status.returncode == 0 and json.loads(status.stdout)["server"]["running"]:
            return client
        time.sleep(0.1)
    client.terminate()
    raise AssertionError("named Herdr server did not start")


def test_named_session_restarts_without_touching_default_session(tmp_path: Path) -> None:
    """A disposable named server restores its own workspace after restart."""
    session = f"issue-10-{os.getpid()}"
    config = tmp_path / "herdr.toml"
    config.write_text("[experimental]\nallow_nested = true\n", encoding="utf-8")
    environment = {**os.environ, "HERDR_CONFIG_PATH": str(config)}
    herdr = ["herdr", "--session", session]
    client: subprocess.Popen[str] | None = None
    try:
        client = start_server(session, environment)
        created = run(
            [
                *herdr,
                "workspace",
                "create",
                "--label",
                "issue-10-test",
                "--cwd",
                str(tmp_path),
                "--no-focus",
            ],
            environment,
        )
        workspace = created["result"]["workspace"]
        run(["herdr", "session", "stop", session, "--json"], environment)
        client.wait(timeout=10)
        client = start_server(session, environment)
        workspaces = run([*herdr, "workspace", "list"], environment)["result"]["workspaces"]
        assert any(item["workspace_id"] == workspace["workspace_id"] for item in workspaces)
    finally:
        subprocess.run(
            ["herdr", "session", "stop", session, "--json"],
            capture_output=True,
            env=environment,
        )
        if client is not None:
            client.wait(timeout=10)
        subprocess.run(
            ["herdr", "session", "delete", session, "--json"],
            capture_output=True,
            env=environment,
        )
