from pathlib import Path

import pytest

from herdr_task_lifecycle.agents.config import AgentDefinition, load_agent_definitions
from herdr_task_lifecycle.errors import LifecycleError


def write_config(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "agents.toml"
    path.write_text(content, encoding="utf-8")
    return path


def test_loads_two_agent_definitions_in_name_order(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        """
        [agents.codex-reviewer]
        role = "reviewer"
        workspace = "dodo5522/ai-agent-home"
        cwd = "/work/review"

        [agents.codex-main]
        role = "implementer"
        workspace = "dodo5522/ai-agent-home"
        cwd = "/work/main"
        """,
    )

    assert load_agent_definitions(path) == (
        AgentDefinition(
            "codex-main", "implementer", "dodo5522/ai-agent-home", Path("/work/main")
        ),
        AgentDefinition(
            "codex-reviewer", "reviewer", "dodo5522/ai-agent-home", Path("/work/review")
        ),
    )


def test_missing_config_returns_no_definitions(tmp_path: Path) -> None:
    assert load_agent_definitions(tmp_path / "missing.toml") == ()


def test_rejects_unknown_fields_before_reconciliation(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        """
        [agents.codex-main]
        role = "implementer"
        workspace = "dodo5522/ai-agent-home"
        cwd = "/work/main"
        model = "gpt-5"
        """,
    )

    with pytest.raises(LifecycleError, match="unknown field.*model"):
        load_agent_definitions(path)


@pytest.mark.parametrize("name", ["Codex-main", "codex_main"])
def test_rejects_invalid_agent_names(tmp_path: Path, name: str) -> None:
    path = write_config(
        tmp_path,
        f"""
        [agents.{name}]
        role = "implementer"
        workspace = "dodo5522/ai-agent-home"
        cwd = "/work/main"
        """,
    )

    with pytest.raises(LifecycleError, match="invalid Agent name"):
        load_agent_definitions(path)


@pytest.mark.parametrize("field", ["role", "workspace", "cwd"])
def test_rejects_empty_required_values(tmp_path: Path, field: str) -> None:
    values = {
        "role": 'role = "implementer"',
        "workspace": 'workspace = "dodo5522/ai-agent-home"',
        "cwd": 'cwd = "/work/main"',
    }
    values[field] = f'{field} = ""'
    path = write_config(
        tmp_path,
        "\n".join(
            [
                "[agents.codex-main]",
                values["role"],
                values["workspace"],
                values["cwd"],
            ]
        ),
    )

    with pytest.raises(LifecycleError, match=f"{field}.*non-empty"):
        load_agent_definitions(path)


def test_rejects_relative_cwd(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        """
        [agents.codex-main]
        role = "implementer"
        workspace = "dodo5522/ai-agent-home"
        cwd = "relative/path"
        """,
    )

    with pytest.raises(LifecycleError, match="cwd.*absolute"):
        load_agent_definitions(path)


def test_rejects_duplicate_agent_tables(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        """
        [agents.codex-main]
        role = "implementer"
        workspace = "dodo5522/ai-agent-home"
        cwd = "/work/main"

        [agents.codex-main]
        role = "reviewer"
        workspace = "dodo5522/ai-agent-home"
        cwd = "/work/review"
        """,
    )

    with pytest.raises(LifecycleError, match="invalid TOML"):
        load_agent_definitions(path)
