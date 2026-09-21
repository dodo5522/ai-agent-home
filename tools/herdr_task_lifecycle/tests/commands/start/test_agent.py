from dataclasses import dataclass, field
from pathlib import Path

import pytest
from herdr_runtime import AgentInfo
from herdr_task_state.model import AgentReference, HerdrReference, Task, TaskKey, Workstream

from herdr_task_lifecycle.commands.start.agent import TaskAgentStarter, task_agent_name
from herdr_task_lifecycle.errors import LifecycleError


def task() -> Task:
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
            )
        },
    )


@dataclass
class FakeHerdr:
    live: list[AgentInfo] = field(default_factory=list)
    started: list[tuple[str, str]] = field(default_factory=list)
    prompts: list[tuple[str, str]] = field(default_factory=list)

    def agents(self) -> list[AgentInfo]:
        return list(self.live)

    def agent_start(self, name: str, pane_id: str, kind: str = "codex") -> AgentInfo:
        self.started.append((name, pane_id))
        agent = AgentInfo(name, kind, pane_id, "w16", Path("/work/issue-9"))
        self.live.append(agent)
        return agent

    def agent_prompt(self, name: str, text: str) -> None:
        self.prompts.append((name, text))


def test_task_agent_starts_and_prompts_once() -> None:
    herdr = FakeHerdr()
    starter = TaskAgentStarter(herdr)
    current = task()
    key = TaskKey(current.repository, current.issue_number)

    first = starter.ensure_implementer(key, current, "w16:p2")
    current = current.model_copy(
        update={
            "workstreams": {
                "main": current.workstreams["main"].model_copy(
                    update={"agents": {"implementer": first}}
                )
            }
        }
    )
    second = starter.ensure_implementer(key, current, "w16:p2")

    assert first == second == AgentReference(name=task_agent_name(key))
    assert herdr.started == [(task_agent_name(key), "w16:p2")]
    assert len(herdr.prompts) == 1
    assert "Issue #9" in herdr.prompts[0][1]
    assert "Agent management" in herdr.prompts[0][1]


def test_existing_unrecorded_agent_is_prompted_for_retry() -> None:
    current = task()
    key = TaskKey(current.repository, current.issue_number)
    herdr = FakeHerdr(
        live=[
            AgentInfo(
                task_agent_name(key), "codex", "w16:p2", "w16", Path("/work/issue-9")
            )
        ]
    )

    TaskAgentStarter(herdr).ensure_implementer(key, current, "w16:p2")

    assert len(herdr.prompts) == 1


def test_existing_agent_on_another_pane_is_not_adopted() -> None:
    current = task()
    key = TaskKey(current.repository, current.issue_number)
    herdr = FakeHerdr(
        live=[AgentInfo(task_agent_name(key), "codex", "w16:p9", "w16", Path("/work/other"))]
    )

    with pytest.raises(LifecycleError, match="different pane"):
        TaskAgentStarter(herdr).ensure_implementer(key, current, "w16:p2")
