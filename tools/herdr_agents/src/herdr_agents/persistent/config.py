"""Load validated, human-maintained Herdr Agent definitions."""

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from ..errors import AgentManagementError

_AGENT_NAME_RE = re.compile(r"[a-z][a-z0-9-]{0,31}\Z")
_FIELDS = frozenset(("role", "workspace", "cwd"))


@dataclass(frozen=True)
class AgentDefinition:
    """Configuration required to reconcile one managed Agent."""

    name: str
    role: str
    workspace: str
    cwd: Path


def _required_string(value: object, field: str, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise AgentManagementError(f"Agent {name} {field} must be non-empty")
    return value


def _parse_definition(name: str, raw: object, path: Path) -> AgentDefinition:
    if _AGENT_NAME_RE.fullmatch(name) is None:
        raise AgentManagementError(f"invalid Agent name {name!r} in {path}")
    if not isinstance(raw, dict):
        raise AgentManagementError(f"Agent {name} definition must be a table in {path}")
    values = cast(Mapping[str, object], raw)
    unknown = sorted(set(values) - _FIELDS)
    if unknown:
        raise AgentManagementError(f"Agent {name} has unknown field {unknown[0]!r} in {path}")
    missing = sorted(_FIELDS - set(values))
    if missing:
        raise AgentManagementError(f"Agent {name} is missing field {missing[0]!r} in {path}")
    role = _required_string(values["role"], "role", name)
    workspace = _required_string(values["workspace"], "workspace", name)
    cwd_value = _required_string(values["cwd"], "cwd", name)
    cwd = Path(cwd_value)
    if not cwd.is_absolute():
        raise AgentManagementError(f"Agent {name} cwd must be absolute in {path}")
    return AgentDefinition(name=name, role=role, workspace=workspace, cwd=cwd)


def load_agent_definitions(path: Path) -> tuple[AgentDefinition, ...]:
    """Load and validate Agent definitions from one TOML file."""
    if not path.exists():
        return ()
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise AgentManagementError(f"invalid TOML configuration {path}") from error
    raw_agents = document.get("agents")
    if raw_agents is None:
        return ()
    if not isinstance(raw_agents, dict):
        raise AgentManagementError(f"agents must be a table in {path}")
    agents = cast(Mapping[str, object], raw_agents)
    return tuple(_parse_definition(name, agents[name], path) for name in sorted(agents))
