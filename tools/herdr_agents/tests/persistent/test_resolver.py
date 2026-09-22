from dataclasses import dataclass, field
from pathlib import Path

import pytest
from herdr_runtime import PaneInfo, WorkspaceInfo

from herdr_agents import AgentManagementError
from herdr_agents.persistent.config import AgentDefinition
from herdr_agents.persistent.resolver import resolve_pane


@dataclass
class FakeWorkspaceClient:
    owner: FakeHerdr

    def list(self) -> list[WorkspaceInfo]:
        return list(self.owner.workspace_values)


@dataclass
class FakePaneClient:
    owner: FakeHerdr

    def list(self, workspace_id: str) -> list[PaneInfo]:
        return [pane for pane in self.owner.pane_values if pane.workspace_id == workspace_id]


@dataclass
class FakeHerdr:
    workspace_values: list[WorkspaceInfo] = field(default_factory=list)
    pane_values: list[PaneInfo] = field(default_factory=list)
    workspace: FakeWorkspaceClient = field(init=False)
    pane: FakePaneClient = field(init=False)

    def __post_init__(self) -> None:
        self.workspace = FakeWorkspaceClient(self)
        self.pane = FakePaneClient(self)


def definition() -> AgentDefinition:
    return AgentDefinition("codex-coordinator", "coordinator", "owner/repo", Path("/work/repo"))


def test_resolves_one_available_pane_by_workspace_and_cwd() -> None:
    herdr = FakeHerdr(
        [WorkspaceInfo("w1", "owner/repo")],
        [PaneInfo("w1:p1", "w1:t1", "w1", Path("/work/repo"), None)],
    )

    assert resolve_pane(definition(), herdr).pane_id == "w1:p1"


@pytest.mark.parametrize(
    ("herdr", "message"),
    [
        (FakeHerdr(), "no Herdr workspace"),
        (
            FakeHerdr([WorkspaceInfo("w1", "owner/repo"), WorkspaceInfo("w2", "owner/repo")]),
            "multiple Herdr workspaces",
        ),
        (FakeHerdr([WorkspaceInfo("w1", "owner/repo")]), "no available Pane"),
        (
            FakeHerdr(
                [WorkspaceInfo("w1", "owner/repo")],
                [
                    PaneInfo("w1:p1", "w1:t1", "w1", Path("/work/repo"), None),
                    PaneInfo("w1:p2", "w1:t1", "w1", Path("/work/repo"), None),
                ],
            ),
            "multiple available Panes",
        ),
    ],
)
def test_rejects_ambiguous_or_missing_target(herdr: FakeHerdr, message: str) -> None:
    with pytest.raises(AgentManagementError, match=message):
        resolve_pane(definition(), herdr)
