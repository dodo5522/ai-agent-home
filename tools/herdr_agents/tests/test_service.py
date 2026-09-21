from dataclasses import dataclass, field
from pathlib import Path

import pytest
from herdr_runtime import AgentInfo

from herdr_agents import AgentManagementError, AgentManager, AgentTarget


@dataclass
class FakeHerdr:
    live: list[AgentInfo] = field(default_factory=list)
    starts: list[tuple[str, str, str]] = field(default_factory=list)
    prompts: list[tuple[str, str]] = field(default_factory=list)
    started_override: AgentInfo | None = None

    def agents(self) -> list[AgentInfo]:
        return list(self.live)

    def agent_start(self, name: str, pane_id: str, kind: str = "codex") -> AgentInfo:
        self.starts.append((name, pane_id, kind))
        return self.started_override or AgentInfo(
            name, kind, pane_id, "w16", Path("/work/issue-9")
        )

    def agent_prompt(self, name: str, text: str) -> None:
        self.prompts.append((name, text))


def target() -> AgentTarget:
    return AgentTarget("codex-issue-9", "w16:p2", "w16", Path("/work/issue-9"))


def test_absent_agent_is_started_on_the_exact_target() -> None:
    herdr = FakeHerdr()

    result = AgentManager(herdr).ensure(target())

    assert result.started is True
    assert result.agent.name == "codex-issue-9"
    assert herdr.starts == [("codex-issue-9", "w16:p2", "codex")]


def test_exact_live_agent_is_reused() -> None:
    existing = AgentInfo("codex-issue-9", "codex", "w16:p2", "w16", Path("/work/issue-9"))
    herdr = FakeHerdr(live=[existing])

    result = AgentManager(herdr).ensure(target())

    assert result.started is False
    assert result.agent == existing
    assert herdr.starts == []


@pytest.mark.parametrize(
    ("existing", "message"),
    [
        (AgentInfo("codex-issue-9", "codex", "w16:p9", "w16", Path("/work/issue-9")), "pane"),
        (AgentInfo("codex-issue-9", "codex", "w16:p2", "w99", Path("/work/issue-9")), "workspace"),
        (AgentInfo("codex-issue-9", "codex", "w16:p2", "w16", Path("/work/other")), "cwd"),
    ],
)
def test_live_agent_with_wrong_identity_is_rejected(
    existing: AgentInfo, message: str
) -> None:
    with pytest.raises(AgentManagementError, match=message):
        AgentManager(FakeHerdr(live=[existing])).ensure(target())


def test_started_agent_with_wrong_identity_is_rejected() -> None:
    herdr = FakeHerdr(
        started_override=AgentInfo(
            "codex-issue-9", "codex", "w16:p9", "w16", Path("/work/issue-9")
        )
    )

    with pytest.raises(AgentManagementError, match="pane"):
        AgentManager(herdr).ensure(target())


def test_prompt_targets_exact_agent_name() -> None:
    herdr = FakeHerdr()

    AgentManager(herdr).prompt("codex-issue-9", "begin")

    assert herdr.prompts == [("codex-issue-9", "begin")]
