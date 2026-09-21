from dataclasses import dataclass, field
from pathlib import Path

import pytest
from herdr_runtime import AgentInfo, PaneInfo

from herdr_agents import AgentManagementError, AgentManager
from herdr_agents.persistent.cli import reconcile
from herdr_agents.persistent.config import AgentDefinition
from herdr_agents.persistent.reconciler import AgentReconcileResult


@dataclass
class FakeHerdr:
    live: list[AgentInfo] = field(default_factory=list)
    starts: list[str] = field(default_factory=list)

    def agents(self) -> list[AgentInfo]:
        return list(self.live)

    def agent_start(self, name: str, pane_id: str, kind: str = "codex") -> AgentInfo:
        self.starts.append(name)
        cwd = Path("/work/main" if name == "codex-main" else "/work/review")
        agent = AgentInfo(name, kind, pane_id, "w1", cwd)
        self.live.append(agent)
        return agent

    def agent_prompt(self, name: str, text: str) -> None:
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


def resolve(definition: AgentDefinition) -> PaneInfo:
    pane_id = "w1:p1" if definition.name == "codex-main" else "w1:p2"
    return PaneInfo(pane_id, "w1:t1", "w1", definition.cwd, None)


def test_reconcile_loads_config_and_is_idempotent(tmp_path: Path) -> None:
    herdr = FakeHerdr()
    manager = AgentManager(herdr)
    config = write_config(tmp_path)

    first = reconcile(config, manager, resolve)
    second = reconcile(config, manager, resolve)

    assert first == AgentReconcileResult(("codex-main", "codex-review"), (), ())
    assert second == AgentReconcileResult((), ("codex-main", "codex-review"), ())


def test_malformed_config_performs_no_agent_mutation(tmp_path: Path) -> None:
    config = tmp_path / "agents.toml"
    config.write_text("[agents", encoding="utf-8")
    herdr = FakeHerdr()

    with pytest.raises(AgentManagementError, match="invalid TOML"):
        reconcile(config, AgentManager(herdr), resolve)

    assert herdr.starts == []
