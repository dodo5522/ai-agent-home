from dataclasses import dataclass, field
from pathlib import Path

from herdr_runtime import AgentInfo, HerdrError, PaneInfo

from herdr_agents import AgentManager, AgentTarget, EnsuredAgent
from herdr_agents.bindings import GitBinding
from herdr_agents.persistent.config import AgentDefinition
from herdr_agents.persistent.reconciler import AgentReconciler, AgentReconcileResult


def definition(name: str, cwd: str) -> AgentDefinition:
    return AgentDefinition(name, "coordinator", "owner/repo", Path(cwd))


@dataclass
class FakeHerdr:
    live: list[AgentInfo] = field(default_factory=list)
    failing: set[str] = field(default_factory=set)
    starts: list[str] = field(default_factory=list)

    def find(self, name: str) -> AgentInfo | None:
        return next((agent for agent in self.live if agent.name == name), None)

    def start(self, name: str, pane_id: str, kind: str = "codex") -> AgentInfo:
        self.starts.append(name)
        if name in self.failing:
            raise HerdrError(f"start failed for {name}")
        cwd = Path("/work/main" if pane_id == "w1:p1" else "/work/review")
        agent = AgentInfo(name, kind, pane_id, "w1", cwd)
        self.live.append(agent)
        return agent

    def prompt(self, name: str, text: str) -> None:
        raise AssertionError("persistent reconcile does not prompt")


def resolve(definition: AgentDefinition, existing: AgentInfo | None) -> PaneInfo:
    del existing
    pane_id = "w1:p1" if definition.cwd == Path("/work/main") else "w1:p2"
    return PaneInfo(pane_id, "w1:t1", "w1", definition.cwd, None)


def test_starts_missing_definitions_and_then_skips_live_agents() -> None:
    herdr = FakeHerdr()
    reconciler = AgentReconciler(AgentManager(herdr), herdr, resolve)
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

    result = AgentReconciler(AgentManager(herdr), herdr, resolve).reconcile(
        [definition("codex-main", "/work/main"), definition("codex-review", "/work/review")]
    )

    assert result.started == ("codex-review",)
    assert result.failed == (("codex-main", "start failed for codex-main"),)
    assert herdr.starts == ["codex-main", "codex-review"]


def test_persistent_reconciliation_uses_complete_git_binding() -> None:
    targets: list[AgentTarget] = []

    class RecordingManager:
        def ensure(self, target: AgentTarget) -> EnsuredAgent:
            targets.append(target)
            return EnsuredAgent(
                AgentInfo(
                    target.name, "codex", target.pane_id, target.workspace_id, target.cwd
                ),
                "fresh",
            )

    result = AgentReconciler(
        RecordingManager(),
        FakeHerdr(),
        resolve,
        lambda cwd: GitBinding("owner/repo", "feat/persistent"),
    ).reconcile([definition("codex-main", "/work/main")])

    assert result.started == ("codex-main",)
    assert targets[0].binding().repository == "owner/repo"
    assert targets[0].binding().workspace_label == "owner/repo"
    assert targets[0].binding().branch == "feat/persistent"
