"""CLI entry point for persistent Herdr Agent reconciliation."""

import argparse
import json
import os
from collections.abc import Callable, Sequence
from pathlib import Path

from herdr_runtime import HerdrClient, HerdrRuntimeError, PaneInfo, SubprocessRunner

from ..errors import AgentManagementError
from ..service import AgentManager
from .config import AgentDefinition, load_agent_definitions
from .reconciler import AgentReconciler, AgentReconcileResult
from .resolver import resolve_pane


def reconcile(
    config_path: Path,
    manager: AgentManager,
    pane_resolver: Callable[[AgentDefinition], PaneInfo],
) -> AgentReconcileResult:
    """Load persistent definitions and reconcile them independently."""
    definitions = load_agent_definitions(config_path)
    return AgentReconciler(manager, pane_resolver).reconcile(definitions)


def _default_config() -> Path:
    return Path(os.environ.get("HERDR_AGENT_CONFIG", ".config/herdr/agents.toml"))


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
    herdr = HerdrClient(SubprocessRunner(), os.environ.get("HERDR_BIN", "herdr"))
    result = reconcile(args.config, AgentManager(herdr), lambda item: resolve_pane(item, herdr))
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
