"""Git and GitHub identity resolution for lifecycle commands."""

import json
import os
import re
from pathlib import Path

from .errors import LifecycleError
from .runner import CommandRunner

_GITHUB_REMOTE_RE = re.compile(
    r"^(?:https://github\.com/|git@github\.com:)([A-Za-z0-9][A-Za-z0-9._-]*)/"
    r"([A-Za-z0-9][A-Za-z0-9._-]*?)(?:\.git)?$"
)
_GITHUB_APP_TOKEN_HELPER = Path.home() / "bin" / "get-github-app-token.py"


def resolve_repository(cwd: Path, runner: CommandRunner) -> str:
    """Resolve the normalized GitHub owner/name from the origin remote."""
    result = runner.run(["git", "-C", str(cwd), "remote", "get-url", "origin"])
    if result.returncode != 0:
        raise LifecycleError("cannot resolve GitHub remote")
    match = _GITHUB_REMOTE_RE.fullmatch(result.stdout.strip())
    if match is None:
        raise LifecycleError("origin is not a supported GitHub remote")
    return f"{match.group(1).lower()}/{match.group(2).lower()}"


def _github_environment(runner: CommandRunner) -> dict[str, str]:
    environment = os.environ.copy()
    if "GH_TOKEN" in environment:
        return environment
    result = runner.run([str(_GITHUB_APP_TOKEN_HELPER)])
    token = result.stdout.strip()
    if result.returncode != 0 or not token:
        raise LifecycleError("cannot load GitHub App token")
    environment["GH_TOKEN"] = token
    return environment


def load_issue_title(repository: str, issue_number: int, runner: CommandRunner) -> str:
    """Load one non-empty Issue title using caller or GitHub App credentials."""
    result = runner.run(
        [
            "gh",
            "issue",
            "view",
            str(issue_number),
            "--repo",
            repository,
            "--json",
            "title",
        ],
        environment=_github_environment(runner),
    )
    if result.returncode != 0:
        raise LifecycleError("cannot load GitHub Issue title")
    try:
        document = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise LifecycleError("GitHub Issue title response is invalid JSON") from error
    if not isinstance(document, dict) or not isinstance(document.get("title"), str):
        raise LifecycleError("GitHub Issue title response is invalid")
    title = document["title"]
    if not title.strip():
        raise LifecycleError("GitHub Issue title is empty")
    return title


def short_title(title: str) -> str:
    """Normalize an Issue title to a deterministic 60-character label."""
    normalized = " ".join(title.split())
    if len(normalized) <= 60:
        return normalized
    return normalized[:59] + "…"
