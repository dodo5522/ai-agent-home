from dataclasses import dataclass, field
from pathlib import Path

from herdr_runtime import AgentInfo, HerdrError, PaneInfo

from herdr_agents import AgentManager
from herdr_agents.persistent.config import AgentDefinition
from herdr_agents.persistent.reconciler import AgentReconciler, AgentReconcileResult


def definition(name: str, cwd: str) -> AgentDefinition:
    return AgentDefinition(name, "coordinator", "owner/repo", Path(cwd))


@dataclass
class FakeHerdr:
    live: list[AgentInfo] = field(default_factory=list)
    failing: set[str] = field(default_factory=set)
    starts: list[str] = field(default_factory=list)

    def agents(self) -> list[AgentInfo]:
        return list(self.live)

    def agent_start(self, name: str, pane_id: str, kind: str = "codex") -> AgentInfo:
        self.starts.append(name)
        if name in self.failing:
            raise HerdrError(f"start failed for {name}")
        cwd = Path("/work/main" if pane_id == "w1:p1" else "/work/review")
        agent = AgentInfo(name, kind, pane_id, "w1", cwd)
        self.live.append(agent)
        return agent

    def agent_prompt(self, name: str, text: str) -> None:
        raise AssertionError("persistent reconcile does not prompt")


def resolve(definition: AgentDefinition, existing: AgentInfo | None) -> PaneInfo:
    del existing
    pane_id = "w1:p1" if definition.cwd == Path("/work/main") else "w1:p2"
    return PaneInfo(pane_id, "w1:t1", "w1", definition.cwd, None)


def test_starts_missing_definitions_and_then_skips_live_agents() -> None:
    herdr = FakeHerdr()
    reconciler = AgentReconciler(AgentManager(herdr), resolve)
    definitions = [
        definition("codex-main", "/work/main"),
        definition("codex-review", "/work/review"),
    ]

    first = reconciler.reconcile(definitions)
    second = reconciler.reconcile(definitions)

    assert first == AgentReconcileResult(("codex-main", "codex-review"), (), ())
    assert second == AgentReconcileResult((), ("codex-main", "codex-review"), ())
    assert herdr.starts == ["codex-main", "codex-review"]


def test_failed_definition_does_not_prevent_later_start() -> None:
    herdr = FakeHerdr(failing={"codex-main"})

    result = AgentReconciler(AgentManager(herdr), resolve).reconcile(
        [definition("codex-main", "/work/main"), definition("codex-review", "/work/review")]
    )

    assert result.started == ("codex-review",)
    assert result.failed == (("codex-main", "start failed for codex-main"),)
    assert herdr.starts == ["codex-main", "codex-review"]
