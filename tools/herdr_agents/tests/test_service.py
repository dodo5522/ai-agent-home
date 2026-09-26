from dataclasses import dataclass, field
from pathlib import Path

import pytest
from herdr_runtime import AgentInfo, HerdrError
from herdr_task_state.sessions import AgentBinding, SessionMapping

from herdr_agents import AgentManagementError, AgentManager, AgentTarget


@dataclass
class FakeHerdr:
    live: list[AgentInfo] = field(default_factory=list)
    starts: list[tuple[str, str, str]] = field(default_factory=list)
    prompts: list[tuple[str, str]] = field(default_factory=list)
    started_override: AgentInfo | None = None
    start_arguments: list[tuple[str, ...]] = field(default_factory=list)
    fail_resume: bool = False
    recover_on_resume: bool = False

    def find(self, name: str) -> AgentInfo | None:
        return next((agent for agent in self.live if agent.name == name), None)

    def start(
        self, name: str, pane_id: str, kind: str = "codex", native_args: tuple[str, ...] = ()
    ) -> AgentInfo:
        self.starts.append((name, pane_id, kind))
        self.start_arguments.append(native_args)
        if self.fail_resume and native_args:
            if self.recover_on_resume:
                self.live.append(
                    AgentInfo(name, kind, pane_id, "w16", Path("/work/issue-9"), native_args[1])
                )
            raise HerdrError("resume failed")
        return self.started_override or AgentInfo(
            name, kind, pane_id, "w16", Path("/work/issue-9"), "fresh-session"
        )

    def prompt(self, name: str, text: str) -> None:
        self.prompts.append((name, text))


def target() -> AgentTarget:
    return AgentTarget("codex-issue-9", "w16:p2", "w16", Path("/work/issue-9"))


def mapped_target() -> AgentTarget:
    return AgentTarget(
        "codex-issue-9",
        "w16:p2",
        "w16",
        Path("/work/issue-9"),
        "owner/repo",
        "owner/repo",
        "feat/x",
    )


def mapping(session_id: str) -> SessionMapping:
    return SessionMapping(mapped_target().binding(), session_id)


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
def test_live_agent_with_wrong_identity_is_rejected(existing: AgentInfo, message: str) -> None:
    with pytest.raises(AgentManagementError, match=message):
        AgentManager(FakeHerdr(live=[existing])).ensure(target())


def test_started_agent_with_wrong_identity_is_rejected() -> None:
    herdr = FakeHerdr(
        started_override=AgentInfo("codex-issue-9", "codex", "w16:p9", "w16", Path("/work/issue-9"))
    )

    with pytest.raises(AgentManagementError, match="pane"):
        AgentManager(herdr).ensure(target())


def test_prompt_targets_exact_agent_name() -> None:
    herdr = FakeHerdr()

    AgentManager(herdr).prompt("codex-issue-9", "begin")

    assert herdr.prompts == [("codex-issue-9", "begin")]

@dataclass
class FakeSessions:
    mapping: SessionMapping | None = None
    recorded: list[tuple[AgentBinding, str]] = field(default_factory=list)
    cleared: list[str] = field(default_factory=list)

    def find_session(self, name: str) -> SessionMapping | None:
        del name
        return self.mapping

    def record_session(self, binding: AgentBinding, session_id: str) -> SessionMapping | None:
        self.recorded.append((binding, session_id))
        return self.mapping

    def clear_session(self, name: str) -> None:
        self.cleared.append(name)


@dataclass
class FakeInspector:
    usable: bool

    def is_usable(self, session_id: str) -> bool:
        del session_id
        return self.usable


def test_absent_agent_resumes_exact_usable_mapping() -> None:
    herdr = FakeHerdr(
        started_override=AgentInfo(
            "codex-issue-9", "codex", "w16:p2", "w16", Path("/work/issue-9"), "session-a"
        )
    )
    state = FakeSessions(mapping("session-a"))

    result = AgentManager(herdr, state, FakeInspector(True)).ensure(mapped_target())

    assert result.disposition == "resumed"
    assert herdr.start_arguments == [("resume", "session-a")]
    assert state.recorded == [(mapped_target().binding(), "session-a")]


def test_unusable_mapping_clears_then_starts_fresh_once() -> None:
    herdr = FakeHerdr()
    state = FakeSessions(mapping("missing"))

    result = AgentManager(herdr, state, FakeInspector(False)).ensure(mapped_target())

    assert result.disposition == "fresh"
    assert state.cleared == ["codex-issue-9"]
    assert herdr.start_arguments == [()]


def test_resume_failure_with_usable_mapping_never_starts_fresh() -> None:
    herdr = FakeHerdr(fail_resume=True)
    state = FakeSessions(mapping("session-a"))

    with pytest.raises(HerdrError, match="resume"):
        AgentManager(herdr, state, FakeInspector(True)).ensure(mapped_target())

    assert herdr.start_arguments == [("resume", "session-a")]


def test_resume_error_accepts_only_exact_live_recovery() -> None:
    herdr = FakeHerdr(fail_resume=True, recover_on_resume=True)
    state = FakeSessions(mapping("session-a"))

    result = AgentManager(herdr, state, FakeInspector(True)).ensure(mapped_target())

    assert result.disposition == "resumed"
    assert result.agent.codex_session_id == "session-a"
    assert herdr.start_arguments == [("resume", "session-a")]
