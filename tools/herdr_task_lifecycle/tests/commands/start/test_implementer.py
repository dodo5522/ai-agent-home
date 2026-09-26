from dataclasses import dataclass, field
from pathlib import Path

import pytest
from herdr_agents import AgentManagementError, AgentTarget, EnsuredAgent
from herdr_runtime import AgentInfo
from herdr_task_state.model import AgentReference, HerdrReference, Task, TaskKey, Workstream

from herdr_task_lifecycle.commands.start.implementer import TaskAgentStarter, task_agent_name


def task(agent: AgentReference | None = None) -> Task:
    agent_fields = {} if agent is None else {"agents": {"implementer": agent}}
    return Task(
        repository="dodo5522/ai-agent-home",
        issue_number=9,
        title="Agent management",
        herdr=HerdrReference(workspace_id="w16", workspace_label="dodo5522/ai-agent-home"),
        workstreams={
            "main": Workstream(
                tab_id="w16:t2",
                tab_label="#9 Agent management",
                worktree="/work/issue-9",
                branch="feat/issue-9-agent-management",
                pane_ids={"root": "w16:p2"},
                **agent_fields,
            )
        },
    )


@dataclass
class FakeManager:
    disposition: str
    session_id: str = "session-a"
    targets: list[AgentTarget] = field(default_factory=list)
    prompts: list[tuple[str, str]] = field(default_factory=list)
    fail_prompt: bool = False

    def ensure(self, target: AgentTarget) -> EnsuredAgent:
        self.targets.append(target)
        return EnsuredAgent(
            AgentInfo(
                target.name,
                "codex",
                target.pane_id,
                target.workspace_id,
                target.cwd,
                self.session_id,
            ),
            self.disposition,
        )

    def prompt(self, name: str, text: str) -> None:
        if self.fail_prompt:
            raise AgentManagementError("prompt failed")
        self.prompts.append((name, text))


def test_new_agent_uses_exact_target_and_receives_initial_prompt() -> None:
    current = task()
    key = TaskKey(current.repository, current.issue_number)
    manager = FakeManager(disposition="fresh")

    reference = TaskAgentStarter(manager).ensure_implementer(key, current, "w16:p2")

    assert reference == AgentReference(name=task_agent_name(key), codex_session_id="session-a")
    assert manager.targets == [
        AgentTarget(
            task_agent_name(key),
            "w16:p2",
            "w16",
            Path("/work/issue-9"),
            "dodo5522/ai-agent-home",
            "dodo5522/ai-agent-home",
            "feat/issue-9-agent-management",
        )
    ]
    assert len(manager.prompts) == 1
    assert "Issue #9" in manager.prompts[0][1]


def test_resumed_agent_does_not_receive_duplicate_prompt() -> None:
    current = task(AgentReference(name="codex-issue-9-stored"))
    key = TaskKey(current.repository, current.issue_number)
    manager = FakeManager(disposition="resumed")

    reference = TaskAgentStarter(manager).ensure_implementer(key, current, "w16:p2")

    assert reference == AgentReference(name="codex-issue-9-stored", codex_session_id="session-a")
    assert manager.prompts == []


def test_unrecorded_live_agent_does_not_receive_initial_prompt() -> None:
    current = task()
    key = TaskKey(current.repository, current.issue_number)
    manager = FakeManager(disposition="live")

    TaskAgentStarter(manager).ensure_implementer(key, current, "w16:p2")

    assert manager.prompts == []


def test_prompt_failure_propagates_before_agent_reference_is_returned() -> None:
    current = task()
    key = TaskKey(current.repository, current.issue_number)

    with pytest.raises(AgentManagementError, match="prompt failed"):
        TaskAgentStarter(FakeManager(disposition="fresh", fail_prompt=True)).ensure_implementer(
            key, current, "w16:p2"
        )
