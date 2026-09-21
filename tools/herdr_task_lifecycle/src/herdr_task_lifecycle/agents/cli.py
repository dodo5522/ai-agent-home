"""CLI entry point for configured Herdr Agent reconciliation."""

import argparse
import json
import os
from collections.abc import Callable, Sequence
from pathlib import Path

from herdr_runtime import HerdrClient, HerdrRuntimeError, SubprocessRunner

from ..errors import LifecycleError
from .config import AgentDefinition, load_agent_definitions
from .reconciler import AgentOperations, AgentReconciler, AgentReconcileResult


def reconcile(
    config_path: Path,
    herdr: AgentOperations,
    pane_resolver: Callable[[AgentDefinition], str],
) -> AgentReconcileResult:
    """Load definitions and reconcile them through injected Herdr operations."""
    definitions = load_agent_definitions(config_path)
    return AgentReconciler(herdr, pane_resolver).reconcile(definitions)


def _pane_resolver(herdr: HerdrClient) -> Callable[[AgentDefinition], str]:
    def resolve(definition: AgentDefinition) -> str:
        matches = [
            workspace for workspace in herdr.workspaces() if workspace.label == definition.workspace
        ]
        if not matches:
            raise LifecycleError(f"no Herdr workspace matches {definition.workspace}")
        if len(matches) > 1:
            raise LifecycleError(f"multiple Herdr workspaces match {definition.workspace}")
        panes = [
            pane
            for pane in herdr.panes(matches[0].workspace_id)
            if pane.cwd == definition.cwd and pane.agent is None
        ]
        if not panes:
            raise LifecycleError(f"no available Pane matches Agent {definition.name}")
        if len(panes) > 1:
            raise LifecycleError(f"multiple available Panes match Agent {definition.name}")
        return panes[0].pane_id

    return resolve


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
    result = reconcile(args.config, herdr, _pane_resolver(herdr))
    print(_result_document(result))
    return 1 if result.failed else 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the configured Agent reconciliation CLI."""
    parser = argparse.ArgumentParser(prog="herdr-agents")
    subparsers = parser.add_subparsers(dest="command", required=True)
    reconcile_parser = subparsers.add_parser("reconcile")
    reconcile_parser.add_argument("--config", type=Path, default=_default_config())
    reconcile_parser.set_defaults(handler=_run)
    try:
        args = parser.parse_args(argv)
        return args.handler(args)
    except (LifecycleError, HerdrRuntimeError) as error:
        parser.error(str(error))
        return 2
