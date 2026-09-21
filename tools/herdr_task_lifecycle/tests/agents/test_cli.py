from pathlib import Path

from herdr_task_lifecycle.agents.cli import reconcile
from herdr_task_lifecycle.agents.config import AgentDefinition
from herdr_task_lifecycle.agents.reconciler import AgentReconcileResult
from herdr_task_lifecycle.herdr import AgentInfo


class FakeHerdr:
    def __init__(self) -> None:
        self.live: list[AgentInfo] = []
        self.started: list[tuple[str, str]] = []
        self.fail_name: str | None = None

    def agents(self) -> list[AgentInfo]:
        return list(self.live)

    def agent_start(self, name: str, pane_id: str, kind: str = "codex") -> AgentInfo:
        self.started.append((name, pane_id))
        if name == self.fail_name:
            from herdr_task_lifecycle.errors import LifecycleError

            raise LifecycleError(f"start failed for {name}")
        agent = AgentInfo(name, kind, pane_id, "w16", Path("/work/main"))
        self.live.append(agent)
        return agent


def write_config(tmp_path: Path) -> Path:
    path = tmp_path / "agents.toml"
    path.write_text(
        """
        [agents.codex-main]
        role = "implementer"
        workspace = "dodo5522/ai-agent-home"
        cwd = "/work/main"

        [agents.codex-reviewer]
        role = "reviewer"
        workspace = "dodo5522/ai-agent-home"
        cwd = "/work/review"
        """,
        encoding="utf-8",
    )
    return path


def pane_resolver(definition: AgentDefinition) -> str:
    return f"w16:{definition.name}"


def test_reconcile_starts_two_configured_agents_and_is_idempotent(tmp_path: Path) -> None:
    herdr = FakeHerdr()
    config = write_config(tmp_path)

    first = reconcile(config, herdr, pane_resolver)
    second = reconcile(config, herdr, pane_resolver)

    assert first == AgentReconcileResult(
        started=("codex-main", "codex-reviewer"), skipped=(), failed=()
    )
    assert second == AgentReconcileResult(
        started=(), skipped=("codex-main", "codex-reviewer"), failed=()
    )
    assert herdr.started == [
        ("codex-main", "w16:codex-main"),
        ("codex-reviewer", "w16:codex-reviewer"),
    ]


def test_reconcile_returns_individual_failure_without_losing_other_start(tmp_path: Path) -> None:
    herdr = FakeHerdr()
    herdr.fail_name = "codex-reviewer"

    result = reconcile(write_config(tmp_path), herdr, pane_resolver)

    assert result.started == ("codex-main",)
    assert result.failed == (("codex-reviewer", "start failed for codex-reviewer"),)


def test_missing_config_is_safe(tmp_path: Path) -> None:
    herdr = FakeHerdr()

    result = reconcile(tmp_path / "missing.toml", herdr, pane_resolver)

    assert result == AgentReconcileResult(started=(), skipped=(), failed=())
