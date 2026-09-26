from dataclasses import dataclass, field
from pathlib import Path

import pytest
from herdr_runtime import CommandResult

from herdr_agents import AgentManagementError
from herdr_agents.bindings import resolve_git_binding


@dataclass
class FakeRunner:
    responses: list[CommandResult]
    calls: list[list[str]] = field(default_factory=list)

    def run(self, arguments: list[str], **_: object) -> CommandResult:
        self.calls.append(arguments)
        return self.responses.pop(0)


def test_resolves_normalized_repository_and_branch() -> None:
    runner = FakeRunner(
        [CommandResult(0, "git@github.com:Owner/Repo.git\n", ""), CommandResult(0, "feat/x\n", "")]
    )

    binding = resolve_git_binding(Path("/work/repo"), runner)

    assert binding.repository == "owner/repo"
    assert binding.branch == "feat/x"


@pytest.mark.parametrize(
    "responses, message",
    [
        ([CommandResult(1, "", "")], "remote"),
        ([CommandResult(0, "https://example.test/repo\n", "")], "supported"),
        (
            [CommandResult(0, "https://github.com/owner/repo.git\n", ""), CommandResult(1, "", "")],
            "branch",
        ),
    ],
)
def test_rejects_incomplete_git_identity(responses: list[CommandResult], message: str) -> None:
    with pytest.raises(AgentManagementError, match=message):
        resolve_git_binding(Path("/work/repo"), FakeRunner(responses))
