from dataclasses import dataclass, field
from pathlib import Path

import pytest
from herdr_runtime import AgentInfo
from herdr_task_state.store import StateStore

from herdr_agents import AgentManagementError, AgentManager, AgentTarget


@dataclass
class FakeHerdr:
    starts: list[tuple[str, str, tuple[str, ...]]] = field(default_factory=list)
    current_targets: dict[str, AgentTarget] = field(default_factory=lambda: targets)

    def find(self, name: str) -> AgentInfo | None:
        del name
        return None

    def start(
        self, name: str, pane_id: str, kind: str = "codex", native_args: tuple[str, ...] = ()
    ) -> AgentInfo:
        self.starts.append((name, pane_id, native_args))
        return AgentInfo(
            name,
            kind,
            pane_id,
            pane_id.split(":")[0],
            self.current_targets[name].cwd,
            native_args[1],
        )

    def prompt(self, name: str, text: str) -> None:
        raise AssertionError(f"unexpected prompt to {name}: {text}")


@dataclass
class UsableSessions:
    def is_usable(self, session_id: str) -> bool:
        return session_id in {"session-alpha", "session-beta"}


targets = {
    "codex-alpha": AgentTarget(
        "codex-alpha",
        "w1:p1",
        "w1",
        Path("/work/project-alpha"),
        "owner/project-alpha",
        "owner/project-alpha",
        "feat/alpha",
    ),
    "codex-beta": AgentTarget(
        "codex-beta",
        "w2:p3",
        "w2",
        Path("/work/project-beta"),
        "owner/project-beta",
        "owner/project-beta",
        "feat/beta",
    ),
}


def test_multiple_agents_resume_their_own_sessions_after_manager_restart(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "herdr-tasks.json")
    store.init()
    prior_targets = {
        name: AgentTarget(
            target.name,
            target.pane_id.replace(":p", ":p-old"),
            target.workspace_id,
            target.cwd,
            target.workspace_label,
            target.repository,
            target.branch,
        )
        for name, target in targets.items()
    }
    store.record_session(prior_targets["codex-alpha"].binding(), "session-alpha")
    store.record_session(prior_targets["codex-beta"].binding(), "session-beta")

    restarted_herdr = FakeHerdr()
    manager = AgentManager(restarted_herdr, store, UsableSessions())
    recovered = [manager.ensure(target) for target in targets.values()]

    assert [
        (item.agent.name, item.agent.pane_id, item.agent.agent_session_id) for item in recovered
    ] == [
        ("codex-alpha", "w1:p1", "session-alpha"),
        ("codex-beta", "w2:p3", "session-beta"),
    ]
    assert restarted_herdr.starts == [
        ("codex-alpha", "w1:p1", ("resume", "session-alpha")),
        ("codex-beta", "w2:p3", ("resume", "session-beta")),
    ]
    mappings = {mapping.binding.name: mapping for mapping in store.list_sessions()}
    assert mappings["codex-alpha"].binding.pane_id == "w1:p1"
    assert mappings["codex-beta"].binding.pane_id == "w2:p3"


def test_changed_project_binding_cannot_resume_a_stored_session(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "herdr-tasks.json")
    store.init()
    original = targets["codex-alpha"]
    store.record_session(original.binding(), "session-alpha")
    moved = AgentTarget(
        original.name,
        original.pane_id,
        "w2",
        Path("/work/project-beta"),
        "owner/project-beta",
        "owner/project-beta",
        "feat/beta",
    )
    restarted_herdr = FakeHerdr()

    with pytest.raises(AgentManagementError, match="binding"):
        AgentManager(restarted_herdr, store, UsableSessions()).ensure(moved)

    assert restarted_herdr.starts == []
    assert store.find_session(original.name) == store.list_sessions()[0]
