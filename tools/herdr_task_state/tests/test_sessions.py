import json
from pathlib import Path

from herdr_task_state.sessions import AgentBinding
from herdr_task_state.store import StateStore


def binding(name: str, worktree: str, branch: str, pane_id: str) -> AgentBinding:
    return AgentBinding(
        name=name,
        repository="dodo5522/ai-agent-home",
        workspace_id="w1",
        workspace_label="dodo5522/ai-agent-home",
        worktree=Path(worktree),
        branch=branch,
        pane_id=pane_id,
    )


def write_state(tmp_path: Path) -> Path:
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps(
            {
                "version": 2,
                "tasks": {
                    "dodo5522/ai-agent-home#10": {
                        "repository": "dodo5522/ai-agent-home",
                        "issue_number": 10,
                        "herdr": {
                            "workspace_id": "w1",
                            "workspace_label": "dodo5522/ai-agent-home",
                        },
                        "workstreams": {
                            "main": {
                                "worktree": "/work/issue-10",
                                "branch": "feat/issue-10",
                                "pane_ids": {"root": "w1:p1"},
                                "agents": {"implementer": {"name": "codex-issue-10"}},
                            }
                        },
                    }
                },
                "persistent_agents": {
                    "codex-coordinator": {
                        "codex_session_id": "session-b",
                        "repository": "dodo5522/ai-agent-home",
                        "workspace_id": "w1",
                        "workspace_label": "dodo5522/ai-agent-home",
                        "worktree": "/work/main",
                        "branch": "main",
                        "pane_id": "w1:p2",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def test_issue_session_update_leaves_another_agent_unchanged(tmp_path: Path) -> None:
    store = StateStore(write_state(tmp_path))

    store.record_session(
        binding("codex-issue-10", "/work/issue-10", "feat/issue-10", "w1:p1"), "session-a"
    )

    assert store.find_session("codex-coordinator") is not None
    assert store.find_session("codex-coordinator").session_id == "session-b"


def test_clear_persistent_mapping_keeps_tasks(tmp_path: Path) -> None:
    store = StateStore(write_state(tmp_path))

    store.clear_session("codex-coordinator")

    assert store.find_session("codex-coordinator") is None
    assert store.get("dodo5522/ai-agent-home#10").issue_number == 10
