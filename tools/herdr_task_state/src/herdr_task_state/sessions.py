"""Typed bindings and mappings for managed Codex sessions."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AgentBinding:
    """Validated placement and repository identity for one managed Agent."""

    name: str
    repository: str
    workspace_id: str
    workspace_label: str
    worktree: Path
    branch: str
    pane_id: str


@dataclass(frozen=True)
class SessionMapping:
    """One stored Codex session and its managed binding."""

    binding: AgentBinding
    session_id: str
