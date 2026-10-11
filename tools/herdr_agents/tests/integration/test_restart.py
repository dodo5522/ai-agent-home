"""Opt-in isolated Herdr session restart coverage."""

import json
import os
import shutil
import subprocess
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest
from herdr_runtime import CommandResult, HerdrClient, HerdrRuntimeError, SubprocessRunner
from herdr_task_state.store import StateStore

from herdr_agents import AgentManagementError, AgentManager, AgentTarget
from herdr_agents.codex_sessions import CodexSessionFiles

pytestmark = pytest.mark.skipif(
    os.environ.get("HERDR_INTEGRATION") != "1",
    reason="set HERDR_INTEGRATION=1 to run isolated Herdr restart coverage",
)


def run(arguments: list[str], environment: dict[str, str]) -> dict[str, object]:
    """Run one command without exposing its output in test diagnostics."""
    completed = subprocess.run(
        arguments, capture_output=True, text=True, check=False, env=environment
    )
    assert completed.returncode == 0, f"command failed: {arguments[1:3]}"
    return json.loads(completed.stdout)


def run_success(arguments: list[str], environment: dict[str, str]) -> None:
    """Run a command whose successful output is not necessarily JSON."""
    completed = subprocess.run(
        arguments, capture_output=True, text=True, check=False, env=environment
    )
    assert completed.returncode == 0, f"command failed: {arguments[1:3]}"


def start_server(session: str, environment: dict[str, str]) -> subprocess.Popen[str]:
    """Attach a disposable client until its detached named server is available."""
    # With piped stdin, script otherwise creates a 0x0 terminal, hiding Codex
    # startup dialogs and preventing Herdr from classifying them correctly.
    client = subprocess.Popen(
        [
            "script",
            "-q",
            "-c",
            f"stty rows 40 cols 120; exec herdr session attach {session}",
            "/dev/null",
        ],
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


def trust_test_repository(codex_home: Path, repository: Path) -> None:
    """Trust one generated test repository only in the disposable Codex home."""
    config = codex_home / "config.toml"
    with config.open("a", encoding="utf-8") as stream:
        stream.write(f'\n[projects.{json.dumps(str(repository))}]\ntrust_level = "trusted"\n')


class NamedSessionRunner:
    """Route every typed Herdr request to one disposable named session."""

    def __init__(self, session: str, environment: Mapping[str, str]) -> None:
        self._session = session
        self._environment = environment
        self._runner = SubprocessRunner()

    def run(
        self,
        arguments: Sequence[str],
        cwd: Path | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> CommandResult:
        return self._runner.run(
            [arguments[0], "--session", self._session, *arguments[1:]],
            cwd,
            self._environment if environment is None else environment,
        )


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


def test_named_session_resumes_two_codex_agents_after_server_restart(tmp_path: Path) -> None:
    """Resume two real Codex sessions on their exact workspaces after restart."""
    session = f"issue-10-codex-{os.getpid()}"
    config = tmp_path / "herdr.toml"
    config.write_text("[experimental]\nallow_nested = true\n", encoding="utf-8")
    state_path = tmp_path / "herdr-tasks.json"
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir(mode=0o700)
    temporary_auth = codex_home / "auth.json"
    environment = {
        **{
            key: value
            for key, value in os.environ.items()
            if key not in {"CODEX_SESSION_ID", "CODEX_THREAD_ID"}
        },
        "CODEX_HOME": str(codex_home),
        "HERDR_CONFIG_PATH": str(config),
    }
    herdr = HerdrClient(NamedSessionRunner(session, environment))
    store = StateStore(state_path)
    client: subprocess.Popen[str] | None = None
    targets: list[AgentTarget] = []
    try:
        source_codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        auth_file = source_codex_home / "auth.json"
        if auth_file.is_file():
            fd = os.open(temporary_auth, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with auth_file.open("rb") as source, os.fdopen(fd, "wb") as destination:
                shutil.copyfileobj(source, destination)
        store.init()
        prepared: list[tuple[str, Path, str]] = []
        for suffix in ("alpha", "beta"):
            worktree = tmp_path / f"repo-{suffix}"
            worktree.mkdir()
            subprocess.run(["git", "init", "--quiet", str(worktree)], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(worktree),
                    "remote",
                    "add",
                    "origin",
                    f"https://github.com/issue-10-test/{suffix}.git",
                ],
                check=True,
            )
            branch = f"feat/{suffix}"
            subprocess.run(
                ["git", "-C", str(worktree), "switch", "--create", branch],
                check=True,
                capture_output=True,
            )
            trust_test_repository(codex_home, worktree)
            prepared.append((suffix, worktree, branch))
        integration = subprocess.run(
            ["herdr", "integration", "install", "codex"],
            capture_output=True,
            text=True,
            check=False,
            env=environment,
        )
        assert integration.returncode == 0, "could not install Codex integration in test home"
        login = subprocess.run(
            ["codex", "login", "status"],
            capture_output=True,
            text=True,
            check=False,
            env=environment,
        )
        assert login.returncode == 0, "temporary CODEX_HOME is not authenticated"
        client = start_server(session, environment)
        for suffix, worktree, branch in prepared:
            repository = f"issue-10-test/{suffix}"
            created = herdr.workspace.create(repository, worktree)
            targets.append(
                AgentTarget(
                    f"codex-issue-10-{suffix}-{os.getpid()}",
                    created.pane_id,
                    created.workspace_id,
                    worktree,
                    repository,
                    repository,
                    branch,
                )
            )

        index_path = codex_home / "session_index.jsonl"
        sessions = CodexSessionFiles(index_path)
        manager = AgentManager(
            herdr.agent,
            store,
            sessions,
            native_args=("--dangerously-bypass-hook-trust",),
        )
        session_ids: dict[str, str] = {}
        for target in targets:
            try:
                herdr.agent.start(
                    target.name,
                    target.pane_id,
                    native_args=("--dangerously-bypass-hook-trust",),
                )
            except HerdrRuntimeError as error:
                blocked = herdr.agent.find(target.name)
                if blocked is None:
                    raise error
                run(
                    ["herdr", "--session", session, "agent", "send-keys", target.name, "enter"],
                    environment,
                )
                run(
                    [
                        "herdr",
                        "--session",
                        session,
                        "agent",
                        "wait",
                        target.name,
                        "--until",
                        "idle",
                        "--timeout",
                        "60000",
                    ],
                    environment,
                )
            manager.ensure(target)
            manager.prompt(target.name, "Reply READY. Do not use tools or change files.")
            observed = manager.wait_for_session(target, timeout_seconds=60)
            if observed.agent_session_id is None:
                raise AssertionError(f"Codex session ID was not reported for {target.name}")
            assert sessions.is_usable(observed.agent_session_id), (
                f"Codex session files are incomplete for {target.name}"
            )
            session_ids[target.name] = observed.agent_session_id
            run(
                [
                    "herdr",
                    "--session",
                    session,
                    "agent",
                    "wait",
                    target.name,
                    "--until",
                    "done",
                    "--timeout",
                    "60000",
                ],
                environment,
            )

        for target in targets:
            run(
                ["herdr", "--session", session, "agent", "send-keys", target.name, "ctrl+c"],
                environment,
            )
            run(
                ["herdr", "--session", session, "agent", "send-keys", target.name, "ctrl+c"],
                environment,
            )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and any(
            herdr.agent.find(target.name) is not None for target in targets
        ):
            time.sleep(0.2)
        assert all(herdr.agent.find(target.name) is None for target in targets), (
            "Codex Agents did not exit before the isolated server restart"
        )
        # Consume terminal control responses emitted as Codex exits before the
        # replacement Agent types its resume command into the shell.
        for target in targets:
            run_success(
                ["herdr", "--session", session, "pane", "run", target.pane_id, "true"],
                environment,
            )

        run(["herdr", "session", "stop", session, "--json"], environment)
        client.wait(timeout=10)
        client = start_server(session, environment)
        manager = AgentManager(
            herdr.agent,
            store,
            CodexSessionFiles(index_path),
            native_args=("--dangerously-bypass-hook-trust",),
        )
        changed = AgentTarget(
            targets[0].name,
            targets[0].pane_id,
            targets[0].workspace_id,
            targets[1].cwd,
            targets[1].workspace_label,
            targets[1].repository,
            targets[1].branch,
        )
        with pytest.raises(AgentManagementError, match="binding"):
            manager.ensure(changed)
        for target in targets:
            recovered = manager.ensure(target)
            assert recovered.disposition == "resumed"
            assert recovered.agent.pane_id == target.pane_id
            assert recovered.agent.workspace_id == target.workspace_id
            assert recovered.agent.cwd == target.cwd
            assert recovered.agent.agent_session_id == session_ids[target.name]

        mappings = {mapping.binding.name: mapping for mapping in store.list_sessions()}
        assert {name: mapping.session_id for name, mapping in mappings.items()} == session_ids
        assert {name: mapping.binding.repository for name, mapping in mappings.items()} == {
            target.name: target.repository for target in targets
        }
        assert {name: mapping.binding.worktree for name, mapping in mappings.items()} == {
            target.name: target.cwd for target in targets
        }
    finally:
        try:
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
        finally:
            temporary_auth.unlink(missing_ok=True)
