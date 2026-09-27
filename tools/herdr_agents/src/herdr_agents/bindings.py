"""Resolve persistent Agent repository bindings from Git."""

import re
from dataclasses import dataclass
from pathlib import Path

from herdr_runtime import CommandRunner

from .errors import AgentManagementError

_GITHUB_REMOTE_RE = re.compile(
    r"^(?:https://github\.com/|git@github\.com:)([A-Za-z0-9][A-Za-z0-9._-]*)/"
    r"([A-Za-z0-9][A-Za-z0-9._-]*?)(?:\.git)?$"
)


@dataclass(frozen=True)
class GitBinding:
    """Repository identity supplied by the worktree's Git metadata."""

    repository: str
    branch: str


def resolve_git_binding(cwd: Path, runner: CommandRunner) -> GitBinding:
    """Return normalized GitHub repository and attached branch for *cwd*."""
    remote = runner.run(["git", "-C", str(cwd), "remote", "get-url", "origin"])
    if remote.returncode != 0:
        raise AgentManagementError("cannot resolve GitHub remote")
    match = _GITHUB_REMOTE_RE.fullmatch(remote.stdout.strip())
    if match is None:
        raise AgentManagementError("origin is not a supported GitHub remote")
    branch = runner.run(["git", "-C", str(cwd), "symbolic-ref", "--quiet", "--short", "HEAD"])
    if branch.returncode != 0 or not branch.stdout.strip():
        raise AgentManagementError("cannot resolve attached Git branch")
    return GitBinding(
        repository=f"{match.group(1).lower()}/{match.group(2).lower()}",
        branch=branch.stdout.strip(),
    )
