from dataclasses import dataclass, field
from pathlib import Path

import pytest
from herdr_runtime import AgentInfo, PaneInfo, WorkspaceInfo

from herdr_agents import AgentManagementError, AgentManager
from herdr_agents.persistent.cli import reconcile
from herdr_agents.persistent.config import AgentDefinition
from herdr_agents.persistent.reconciler import AgentReconcileResult
from herdr_agents.persistent.resolver import resolve_pane


@dataclass
class FakeWorkspaceClient:
    owner: FakeHerdr

    def list(self) -> list[WorkspaceInfo]:
        return list(self.owner.workspace_values)


@dataclass
class FakePaneClient:
    owner: FakeHerdr

    def list(self, workspace_id: str) -> list[PaneInfo]:
        return [pane for pane in self.owner.pane_values if pane.workspace_id == workspace_id]


@dataclass
class FakeHerdr:
    live: list[AgentInfo] = field(default_factory=list)
    starts: list[str] = field(default_factory=list)
    workspace_values: list[WorkspaceInfo] = field(default_factory=list)
    pane_values: list[PaneInfo] = field(default_factory=list)
    workspace: FakeWorkspaceClient = field(init=False)
    pane: FakePaneClient = field(init=False)

    def __post_init__(self) -> None:
        self.workspace = FakeWorkspaceClient(self)
        self.pane = FakePaneClient(self)

    def find(self, name: str) -> AgentInfo | None:
        return next((agent for agent in self.live if agent.name == name), None)

    def start(self, name: str, pane_id: str, kind: str = "codex") -> AgentInfo:
        self.starts.append(name)
        cwd = Path("/work/main" if name == "codex-main" else "/work/review")
        agent = AgentInfo(name, kind, pane_id, "w1", cwd)
        self.live.append(agent)
        return agent

    def prompt(self, name: str, text: str) -> None:
        raise AssertionError("persistent reconcile does not prompt")


def write_config(tmp_path: Path) -> Path:
    path = tmp_path / "agents.toml"
    path.write_text(
        """
        [agents.codex-main]
        role = "coordinator"
        workspace = "owner/repo"
        cwd = "/work/main"

        [agents.codex-review]
        role = "coordinator"
        workspace = "owner/repo"
        cwd = "/work/review"
        """,
        encoding="utf-8",
    )
    return path


def resolve(definition: AgentDefinition, existing: AgentInfo | None) -> PaneInfo:
    del existing
    pane_id = "w1:p1" if definition.name == "codex-main" else "w1:p2"
    return PaneInfo(pane_id, "w1:t1", "w1", definition.cwd, None)


def test_reconcile_loads_config_and_is_idempotent(tmp_path: Path) -> None:
    herdr = FakeHerdr()
    manager = AgentManager(herdr)
    config = write_config(tmp_path)

    first = reconcile(config, manager, herdr, resolve)
    second = reconcile(config, manager, herdr, resolve)

    assert first == AgentReconcileResult(("codex-main", "codex-review"), (), ())
    assert second == AgentReconcileResult((), ("codex-main", "codex-review"), ())


def test_malformed_config_performs_no_agent_mutation(tmp_path: Path) -> None:
    config = tmp_path / "agents.toml"
    config.write_text("[agents", encoding="utf-8")
    herdr = FakeHerdr()

    with pytest.raises(AgentManagementError, match="invalid TOML"):
        reconcile(config, AgentManager(herdr), herdr, resolve)

    assert herdr.starts == []


def test_live_configured_agent_is_skipped_before_resolving_an_available_pane(
    tmp_path: Path,
) -> None:
    config = tmp_path / "agents.toml"
    config.write_text(
        """
        [agents.codex-main]
        role = "coordinator"
        workspace = "owner/repo"
        cwd = "/work/main"
        """,
        encoding="utf-8",
    )
    herdr = FakeHerdr(
        live=[AgentInfo("codex-main", "codex", "w1:p1", "w1", Path("/work/main"))],
        workspace_values=[WorkspaceInfo("w1", "owner/repo")],
        pane_values=[PaneInfo("w1:p1", "w1:t1", "w1", Path("/work/main"), "codex")],
    )

    result = reconcile(
        config,
        AgentManager(herdr),
        herdr,
        lambda item, existing: resolve_pane(
            item,
            herdr,
            None if existing is None else existing.pane_id,
        ),
    )

    assert result == AgentReconcileResult((), ("codex-main",), ())
