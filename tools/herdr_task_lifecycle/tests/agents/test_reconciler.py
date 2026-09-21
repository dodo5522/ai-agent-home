from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from herdr_task_lifecycle.agents.config import AgentDefinition
from herdr_task_lifecycle.agents.reconciler import AgentReconciler
from herdr_task_lifecycle.errors import LifecycleError
from herdr_task_lifecycle.herdr import AgentInfo


def definition(name: str) -> AgentDefinition:
    return AgentDefinition(name, "implementer", "dodo5522/ai-agent-home", Path("/work/main"))


@dataclass
class FakeHerdr:
    live: list[AgentInfo] = field(default_factory=list)
    started: list[tuple[str, str]] = field(default_factory=list)
    failing: set[str] = field(default_factory=set)

    def agents(self) -> list[AgentInfo]:
        return list(self.live)

    def agent_start(self, name: str, pane_id: str, kind: str = "codex") -> AgentInfo:
        self.started.append((name, pane_id))
        if name in self.failing:
            raise LifecycleError(f"start failed for {name}")
        agent = AgentInfo(name, kind, pane_id, "w16", Path("/work/main"))
        self.live.append(agent)
        return agent


@pytest.fixture
def resolve_pane() -> Callable[[AgentDefinition], str]:
    def resolver(agent: AgentDefinition) -> str:
        return f"w16:{agent.name}"

    return resolver


def test_starts_two_missing_agents_independently(
    resolve_pane: Callable[[AgentDefinition], str],
) -> None:
    herdr = FakeHerdr()
    result = AgentReconciler(herdr, resolve_pane).reconcile(
        [definition("codex-main"), definition("codex-reviewer")]
    )

    assert result.started == ("codex-main", "codex-reviewer")
    assert result.skipped == ()
    assert result.failed == ()
    assert herdr.started == [
        ("codex-main", "w16:codex-main"),
        ("codex-reviewer", "w16:codex-reviewer"),
    ]


def test_second_reconcile_skips_both_live_agents(
    resolve_pane: Callable[[AgentDefinition], str],
) -> None:
    herdr = FakeHerdr()
    reconciler = AgentReconciler(herdr, resolve_pane)
    definitions = [definition("codex-main"), definition("codex-reviewer")]

    reconciler.reconcile(definitions)
    result = reconciler.reconcile(definitions)

    assert result.started == ()
    assert result.skipped == ("codex-main", "codex-reviewer")
    assert len(herdr.started) == 2


def test_restarts_only_one_missing_agent(
    resolve_pane: Callable[[AgentDefinition], str],
) -> None:
    herdr = FakeHerdr(
        live=[AgentInfo("codex-main", "codex", "w16:main", "w16", Path("/work/main"))]
    )

    result = AgentReconciler(herdr, resolve_pane).reconcile(
        [definition("codex-main"), definition("codex-reviewer")]
    )

    assert result.started == ("codex-reviewer",)
    assert result.skipped == ("codex-main",)
    assert herdr.started == [("codex-reviewer", "w16:codex-reviewer")]


def test_failed_agent_does_not_affect_another_agent(
    resolve_pane: Callable[[AgentDefinition], str],
) -> None:
    herdr = FakeHerdr(failing={"codex-reviewer"})

    result = AgentReconciler(herdr, resolve_pane).reconcile(
        [definition("codex-main"), definition("codex-reviewer")]
    )

    assert result.started == ("codex-main",)
    assert result.failed == (("codex-reviewer", "start failed for codex-reviewer"),)
    assert herdr.started == [
        ("codex-main", "w16:codex-main"),
        ("codex-reviewer", "w16:codex-reviewer"),
    ]


def test_bare_codex_does_not_satisfy_named_agent(
    resolve_pane: Callable[[AgentDefinition], str],
) -> None:
    herdr = FakeHerdr(
        live=[AgentInfo("codex", "codex", "w16:p1", "w16", Path("/work/main"))]
    )

    result = AgentReconciler(herdr, resolve_pane).reconcile([definition("codex-main")])

    assert result.started == ("codex-main",)
    assert result.skipped == ()
