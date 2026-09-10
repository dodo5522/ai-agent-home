"""Pydantic models, parsing, and validation for Herdr task state."""

import json
import re
from dataclasses import dataclass
from typing import Annotated, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)


class StateValidationError(ValueError):
    """Raised when task-state input violates its public schema."""


_REPOSITORY_PATTERN = r"[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*"
_SLUG_PATTERN = r"[a-z][a-z0-9-]{0,31}"
_TASK_KEY_RE = re.compile(rf"({_REPOSITORY_PATTERN})#([1-9][0-9]*)")
_SLUG_RE = re.compile(_SLUG_PATTERN)


def _absolute_path(value: str) -> str:
    if not value.startswith("/"):
        raise ValueError("must be an absolute path")
    return value


NonEmptyString = Annotated[str, StringConstraints(min_length=1)]
RepositoryName = Annotated[str, StringConstraints(pattern=_REPOSITORY_PATTERN)]
Slug = Annotated[str, StringConstraints(pattern=_SLUG_PATTERN)]
PositiveInt = Annotated[StrictInt, Field(gt=0)]
AbsolutePath = Annotated[NonEmptyString, AfterValidator(_absolute_path)]


@dataclass(frozen=True)
class TaskKey:
    """Stable repository and issue identifier for a task."""

    repository: str
    issue_number: int

    def __str__(self) -> str:
        return f"{self.repository}#{self.issue_number}"

    @classmethod
    def parse(cls, value: str) -> Self:
        """Parse a stable task key into its repository and issue parts."""
        if not isinstance(value, str):
            raise StateValidationError("task key must be a string")
        match = _TASK_KEY_RE.fullmatch(value)
        if match is None:
            raise StateValidationError("task key must be owner/repository#positive-issue-number")
        return cls(repository=match.group(1), issue_number=int(match.group(2)))


class Model(BaseModel):
    """Base Pydantic model with shared JSON serialization and parsing behavior."""

    model_config = ConfigDict(extra="allow", strict=True, allow_inf_nan=False)

    def to_json(self) -> str:
        """Serialize this model to its public JSON representation."""
        return self.model_dump_json(indent=2, exclude_unset=True, ensure_ascii=False)

    @staticmethod
    def _validate_slug_keys[V](values: dict[str, V]) -> dict[str, V]:
        if any(_SLUG_RE.fullmatch(key) is None for key in values):
            raise ValueError("keys must be lower-case slugs")
        return values

    @staticmethod
    def _reject_non_standard_constant(value: str) -> None:
        raise ValueError(f"non-standard JSON constant: {value}")

    @staticmethod
    def _safe_validation_message(error: ValidationError) -> str:
        details = error.errors(include_context=False, include_input=False, include_url=False)
        return "; ".join(
            f"{'.'.join(str(part) for part in detail['loc']) or 'document'}: {detail['msg']}"
            for detail in details
        )

    @classmethod
    def _parse(cls, payload: str) -> Self:
        try:
            document = json.loads(payload, parse_constant=cls._reject_non_standard_constant)
            return cls.model_validate(document)
        except ValidationError as error:
            raise StateValidationError(cls._safe_validation_message(error)) from error
        except (json.JSONDecodeError, ValueError) as error:
            raise StateValidationError("input must be one strict JSON document") from error


class AgentReference(Model):
    """Reference data for an agent associated with a workstream."""

    name: NonEmptyString
    codex_session_id: NonEmptyString | None = None

    @field_validator("codex_session_id", mode="before")
    @classmethod
    def reject_null_session_id(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("must be a non-empty string when present")
        return value


class HerdrReference(Model):
    """Reference data for the Herdr workspace associated with a task."""

    workspace_id: NonEmptyString | None = None
    workspace_label: NonEmptyString | None = None

    @field_validator("workspace_id", "workspace_label", mode="before")
    @classmethod
    def reject_null_reference(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("must be a non-empty string when present")
        return value


class Workstream(Model):
    """State and Herdr resources associated with one task workstream."""

    tab_id: NonEmptyString | None = None
    tab_label: NonEmptyString | None = None
    worktree: AbsolutePath | None = None
    branch: NonEmptyString | None = None
    pull_requests: list[PositiveInt] | None = None
    pane_ids: dict[Slug, NonEmptyString] | None = None
    agents: dict[Slug, AgentReference] | None = None

    @field_validator("tab_id", "tab_label", "worktree", "branch", mode="before")
    @classmethod
    def reject_null_string_field(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("must be omitted instead of null")
        return value

    @field_validator("pull_requests", "pane_ids", "agents", mode="before")
    @classmethod
    def reject_null_collection_field(
        cls,
        value: list[PositiveInt] | dict[str, NonEmptyString] | dict[str, AgentReference] | None,
    ) -> list[PositiveInt] | dict[str, NonEmptyString] | dict[str, AgentReference]:
        if value is None:
            raise ValueError("must be omitted instead of null")
        return value

    @field_validator("pane_ids")
    @classmethod
    def validate_pane_id_keys(cls, values: dict[str, NonEmptyString]) -> dict[str, NonEmptyString]:
        return cls._validate_slug_keys(values)

    @field_validator("agents")
    @classmethod
    def validate_agent_keys(cls, values: dict[str, AgentReference]) -> dict[str, AgentReference]:
        return cls._validate_slug_keys(values)

    @field_validator("pull_requests")
    @classmethod
    def require_unique_pull_requests(cls, values: list[PositiveInt]) -> list[PositiveInt]:
        if len(values) != len(set(values)):
            raise ValueError("must contain unique positive integers")
        return values


class Task(Model):
    """Task metadata and its main or parallel workstreams."""

    repository: RepositoryName
    issue_number: PositiveInt
    title: NonEmptyString | None = None
    herdr: HerdrReference | None = None
    workstreams: dict[Slug, Workstream]

    @field_validator("title", "herdr", mode="before")
    @classmethod
    def reject_null_optional_field(cls, value: str | HerdrReference | None) -> str | HerdrReference:
        if value is None:
            raise ValueError("must be omitted instead of null")
        return value

    @field_validator("workstreams")
    @classmethod
    def validate_workstream_keys(cls, values: dict[str, Workstream]) -> dict[str, Workstream]:
        return cls._validate_slug_keys(values)

    @model_validator(mode="after")
    def require_main_workstream(self) -> Self:
        if "main" not in self.workstreams:
            raise ValueError("must contain the main workstream")
        return self

    def assert_matches(self, task_key: TaskKey) -> None:
        """Ensure this task's identity matches the supplied stable task key."""
        if self.repository != task_key.repository or self.issue_number != task_key.issue_number:
            raise StateValidationError("task repository and issue number must match its task key")

    @classmethod
    def parse(cls, task_key: str, payload: str) -> Self:
        """Parse one task document and verify its identity against a task key."""
        task = cls._parse(payload)
        identity = TaskKey.parse(task_key)
        task.assert_matches(identity)
        return task


class TaskState(Model):
    """Versioned collection of validated tasks keyed by stable task identifiers."""

    version: Annotated[StrictInt, Field(ge=1, le=1)]
    tasks: dict[str, Task]

    @model_validator(mode="after")
    def validate_task_identities(self) -> Self:
        for task_key, task in self.tasks.items():
            task.assert_matches(TaskKey.parse(task_key))
        return self

    @classmethod
    def parse(cls, payload: str) -> Self:
        """Parse and validate a complete task-state JSON document."""
        return cls._parse(payload)

    def get_task(self, task_key: TaskKey) -> Task:
        """Return the task identified by a stable task key."""
        try:
            return self.tasks[str(task_key)]
        except KeyError as error:
            raise KeyError(str(task_key)) from error

    def with_task(self, task_key: TaskKey, task: Task) -> Self:
        """Return a state copy containing the supplied task."""
        task.assert_matches(task_key)
        return self.model_copy(update={"tasks": {**self.tasks, str(task_key): task}})

    def without_task(self, task_key: TaskKey) -> Self:
        """Return a state copy without the supplied task, if present."""
        if str(task_key) not in self.tasks:
            return self
        remaining = {key: value for key, value in self.tasks.items() if key != str(task_key)}
        return self.model_copy(update={"tasks": remaining})


__all__ = [
    "AgentReference",
    "HerdrReference",
    "Model",
    "StateValidationError",
    "Task",
    "TaskKey",
    "TaskState",
    "Workstream",
]
