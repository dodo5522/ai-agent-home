"""CLI entry point for persistent Herdr Agent reconciliation."""

import argparse
import json
import os
from collections.abc import Callable, Sequence
from pathlib import Path

from herdr_runtime import AgentInfo, HerdrClient, HerdrRuntimeError, PaneInfo, SubprocessRunner
from herdr_task_state.store import StateStore

from ..bindings import resolve_git_binding
from ..codex_sessions import CodexSessionFiles
from ..errors import AgentManagementError
from ..service import AgentManager, AgentOperations
from .config import AgentDefinition, load_agent_definitions
from .reconciler import AgentReconciler, AgentReconcileResult
from .resolver import resolve_pane


def reconcile(
    config_path: Path,
    manager: AgentManager,
    agents: AgentOperations,
    pane_resolver: Callable[[AgentDefinition, AgentInfo | None], PaneInfo],
) -> AgentReconcileResult:
    """Load persistent definitions and reconcile them independently."""
    definitions = load_agent_definitions(config_path)
    return AgentReconciler(manager, agents, pane_resolver).reconcile(definitions)


def _default_config() -> Path:
    return Path(os.environ.get("HERDR_AGENT_CONFIG", ".config/herdr/agents.toml"))


def _default_state_path() -> Path:
    state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    default = state_home / "ai-agent-home" / "herdr-tasks.json"
    return Path(os.environ.get("HERDR_TASK_STATE_FILE", default))


def _result_document(result: AgentReconcileResult) -> str:
    return json.dumps(
        {
            "started": list(result.started),
            "skipped": list(result.skipped),
            "failed": [{"name": name, "error": error} for name, error in result.failed],
        },
        ensure_ascii=False,
    )


def _run(args: argparse.Namespace) -> int:
    runner = SubprocessRunner()
    herdr = HerdrClient(runner, os.environ.get("HERDR_BIN", "herdr"))
    state = StateStore(_default_state_path())
    state.init()
    result = reconcile(
        args.config,
        AgentManager(
            herdr.agent,
            state,
            CodexSessionFiles(Path.home() / ".codex" / "session_index.jsonl"),
        ),
        herdr.agent,
        lambda item, existing: resolve_pane(
            item,
            herdr,
            None if existing is None else existing.pane_id,
        ),
        lambda cwd: resolve_git_binding(cwd, runner),
    )
    print(_result_document(result))
    return 1 if result.failed else 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the persistent Agent reconciliation CLI."""
    parser = argparse.ArgumentParser(prog="herdr-agents")
    subparsers = parser.add_subparsers(dest="command", required=True)
    reconcile_parser = subparsers.add_parser("reconcile")
    reconcile_parser.add_argument("--config", type=Path, default=_default_config())
    reconcile_parser.set_defaults(handler=_run)
    try:
        args = parser.parse_args(argv)
        return args.handler(args)
    except (AgentManagementError, HerdrRuntimeError) as error:
        parser.error(str(error))
        return 2
