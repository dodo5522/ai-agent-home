"""Filesystem-backed, locked Herdr task-state storage."""

import fcntl
import os
import stat
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from .model import (
    AgentReference,
    PersistentAgentReference,
    StateValidationError,
    Task,
    TaskKey,
    TaskState,
    migrate_state,
)
from .sessions import AgentBinding, SessionMapping


class StateFilesystemError(RuntimeError):
    """Raised when task-state storage cannot perform a filesystem operation."""

    pass


class StateFileLock:
    """Manage the adjacent lock file for a state document."""

    def __init__(self, state_path: Path) -> None:
        if not state_path.is_absolute():
            raise StateFilesystemError(f"state path must be absolute: {state_path}")
        self._state_path = state_path
        self._lock_path = Path(f"{state_path}.lock")

    def _ensure_parent(self) -> None:
        try:
            self._state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(self._state_path.parent, 0o700)
        except OSError as exc:
            raise StateFilesystemError(
                f"cannot create state directory: {self._state_path}"
            ) from exc

    def _acquire(self) -> int:
        self._ensure_parent()
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        fd = -1
        try:
            fd = os.open(self._lock_path, flags, 0o600)
            os.fchmod(fd, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX)
            return fd
        except OSError as exc:
            if fd >= 0:
                os.close(fd)
            raise StateFilesystemError(f"cannot lock state file: {self._state_path}") from exc

    @staticmethod
    def _release(fd: int) -> None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    @contextmanager
    def locked(self) -> Generator:
        """Hold the state lock for the duration of a context."""
        fd = self._acquire()
        try:
            yield
        finally:
            self._release(fd)


class StateStore:
    """Filesystem-backed storage for validated Herdr task state."""

    def __init__(self, path: Path) -> None:
        if not path.is_absolute():
            raise StateFilesystemError(f"state path must be absolute: {path}")
        self.path = path
        self._state_lock = StateFileLock(path)

    def _read(self) -> TaskState:
        try:
            st = self.path.lstat()
        except FileNotFoundError as exc:
            raise StateFilesystemError(f"state file does not exist: {self.path}") from exc
        except OSError as exc:
            raise StateFilesystemError(f"cannot read state file: {self.path}") from exc
        if not stat.S_ISREG(st.st_mode):
            raise StateFilesystemError(f"cannot read state file: {self.path}")
        try:
            with self.path.open("r", encoding="utf-8") as stream:
                return TaskState.parse(stream.read())
        except StateValidationError as exc:
            raise StateValidationError(f"invalid state file: {self.path}") from exc
        except (OSError, UnicodeError) as exc:
            raise StateFilesystemError(f"cannot read state file: {self.path}") from exc

    @staticmethod
    def _empty() -> TaskState:
        return TaskState(version=2, tasks={}, persistent_agents={})

    @staticmethod
    def _encode(document: TaskState) -> bytes:
        return (document.to_json() + "\n").encode("utf-8")

    def _write(self, document: TaskState) -> None:
        fd = -1
        temporary = None
        try:
            fd, temporary = tempfile.mkstemp(prefix=".herdr-tasks.", dir=self.path.parent)
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as stream:
                fd = -1
                stream.write(self._encode(document))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            temporary = None
            os.chmod(self.path, 0o600)
        except OSError as exc:
            raise StateFilesystemError(f"cannot replace state file: {self.path}") from exc
        finally:
            if fd >= 0:
                os.close(fd)
            if temporary:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass

    def init(self) -> None:
        """Create or validate the state file without overwriting valid data."""
        with self._state_lock.locked():
            try:
                st = self.path.lstat()
            except FileNotFoundError:
                self._write(self._empty())
                return
            except OSError as exc:
                raise StateFilesystemError(f"cannot read state file: {self.path}") from exc
            if not stat.S_ISREG(st.st_mode):
                raise StateFilesystemError(f"cannot read state file: {self.path}")
            self._read()
            try:
                os.chmod(self.path, 0o600)
            except OSError as exc:
                raise StateFilesystemError(f"cannot secure state file: {self.path}") from exc

    def read(self) -> TaskState:
        """Read and validate the complete state document."""
        return self._read()

    def get(self, task_key: str) -> Task:
        """Return one task by its stable task key."""
        key = TaskKey.parse(task_key)
        document = self._read()
        try:
            return document.get_task(key)
        except KeyError as error:
            raise KeyError(task_key) from error

    def _writable_document(self) -> TaskState:
        current = self._read() if self.path.exists() or self.path.is_symlink() else self._empty()
        return migrate_state(current)

    @staticmethod
    def _mapping_for_task_agent(
        task_key: str, task: Task, role: str, binding: AgentBinding | None = None
    ) -> SessionMapping | None:
        del task_key
        for workstream in task.workstreams.values():
            for candidate_role, agent in (workstream.agents or {}).items():
                if candidate_role != role:
                    continue
                if binding is not None and agent.name != binding.name:
                    continue
                if (
                    task.herdr is None
                    or task.herdr.workspace_id is None
                    or task.herdr.workspace_label is None
                ):
                    raise StateValidationError("Agent binding is incomplete")
                if workstream.worktree is None or workstream.branch is None:
                    raise StateValidationError("Agent binding is incomplete")
                pane_id = (workstream.pane_ids or {}).get(candidate_role) or (
                    workstream.pane_ids or {}
                ).get("root")
                if pane_id is None:
                    raise StateValidationError("Agent binding is incomplete")
                target = AgentBinding(
                    agent.name,
                    task.repository,
                    task.herdr.workspace_id,
                    task.herdr.workspace_label,
                    Path(workstream.worktree),
                    workstream.branch,
                    pane_id,
                )
                if agent.codex_session_id is None:
                    return None
                return SessionMapping(target, agent.codex_session_id)
        return None

    @staticmethod
    def _matches(left: AgentBinding, right: AgentBinding) -> bool:
        return left == right

    @staticmethod
    def _persistent_mapping(name: str, agent: PersistentAgentReference) -> SessionMapping:
        binding = AgentBinding(
            name,
            agent.repository,
            agent.workspace_id,
            agent.workspace_label,
            Path(agent.worktree),
            agent.branch,
            agent.pane_id,
        )
        return SessionMapping(binding, agent.codex_session_id)

    def find_session(self, name: str) -> SessionMapping | None:
        """Return the exact stored session mapping without mutating state."""
        document = self._read()
        for task in document.tasks.values():
            for workstream in task.workstreams.values():
                for role, agent in (workstream.agents or {}).items():
                    if agent.name == name:
                        return self._mapping_for_task_agent("", task, role)
        persistent = (document.persistent_agents or {}).get(name)
        return None if persistent is None else self._persistent_mapping(name, persistent)

    def list_sessions(self) -> list[SessionMapping]:
        """List stored mappings without migrating or modifying state."""
        document = self._read()
        mappings: list[SessionMapping] = []
        for task in document.tasks.values():
            for workstream in task.workstreams.values():
                for role in workstream.agents or {}:
                    mapping = self._mapping_for_task_agent("", task, role)
                    if mapping is not None:
                        mappings.append(mapping)
        for name, agent in (document.persistent_agents or {}).items():
            mappings.append(self._persistent_mapping(name, agent))
        return sorted(mappings, key=lambda mapping: mapping.binding.name)

    def record_session(self, binding: AgentBinding, session_id: str) -> SessionMapping:
        """Atomically record an exact session mapping after binding validation."""
        if not binding.name or not session_id:
            raise StateValidationError("Agent name and session ID must be non-empty")
        with self._state_lock.locked():
            current = self._writable_document()
            for task_key, task in current.tasks.items():
                for workstream_name, workstream in task.workstreams.items():
                    for role, agent in (workstream.agents or {}).items():
                        if agent.name != binding.name:
                            continue
                        self._mapping_for_task_agent(task_key, task, role, binding)
                        expected = AgentBinding(
                            agent.name,
                            task.repository,
                            task.herdr.workspace_id if task.herdr else "",
                            task.herdr.workspace_label if task.herdr else "",
                            Path(workstream.worktree or ""),
                            workstream.branch or "",
                            (workstream.pane_ids or {}).get(role)
                            or (workstream.pane_ids or {}).get("root", ""),
                        )
                        if not self._matches(expected, binding):
                            raise StateValidationError("Agent binding does not match state")
                        updated_agent = AgentReference(name=agent.name, codex_session_id=session_id)
                        updated_agents = {**(workstream.agents or {}), role: updated_agent}
                        updated_workstream = workstream.model_copy(
                            update={"agents": updated_agents}
                        )
                        updated_task = task.model_copy(
                            update={
                                "workstreams": {
                                    **task.workstreams,
                                    workstream_name: updated_workstream,
                                }
                            }
                        )
                        updated = current.with_task(TaskKey.parse(task_key), updated_task)
                        validated = TaskState.model_validate(
                            updated.model_dump(mode="python", exclude_none=True)
                        )
                        self._write(validated)
                        return SessionMapping(binding, session_id)
            persistent = (current.persistent_agents or {}).get(binding.name)
            if persistent is not None and not self._matches(
                self._persistent_mapping(binding.name, persistent).binding, binding
            ):
                raise StateValidationError("Agent binding does not match state")
            records = dict(current.persistent_agents or {})
            records[binding.name] = PersistentAgentReference(
                codex_session_id=session_id,
                repository=binding.repository,
                workspace_id=binding.workspace_id,
                workspace_label=binding.workspace_label,
                worktree=str(binding.worktree),
                branch=binding.branch,
                pane_id=binding.pane_id,
            )
            validated = TaskState.model_validate(
                current.model_dump(mode="python", exclude_none=True)
                | {"persistent_agents": records}
            )
            self._write(validated)
            return SessionMapping(binding, session_id)

    def clear_session(self, name: str) -> None:
        """Remove one exact mapping without affecting task resources."""
        with self._state_lock.locked():
            current = self._writable_document()
            for task_key, task in current.tasks.items():
                for workstream_name, workstream in task.workstreams.items():
                    for role, agent in (workstream.agents or {}).items():
                        if agent.name != name:
                            continue
                        updated_agents = {
                            **(workstream.agents or {}),
                            role: AgentReference(name=agent.name),
                        }
                        updated_workstream = workstream.model_copy(
                            update={"agents": updated_agents}
                        )
                        updated_task = task.model_copy(
                            update={
                                "workstreams": {
                                    **task.workstreams,
                                    workstream_name: updated_workstream,
                                }
                            }
                        )
                        self._write(
                            TaskState.model_validate(
                                current.with_task(TaskKey.parse(task_key), updated_task).model_dump(
                                    mode="python", exclude_none=True
                                )
                            )
                        )
                        return
            if name not in (current.persistent_agents or {}):
                raise KeyError(name)
            records = {
                key: value
                for key, value in (current.persistent_agents or {}).items()
                if key != name
            }
            self._write(
                TaskState.model_validate(
                    current.model_dump(mode="python", exclude_none=True)
                    | {"persistent_agents": records}
                )
            )

    def put(self, task_key: str, task: Task) -> Task:
        """Validate and atomically store one task under its stable key."""
        key = TaskKey.parse(task_key)
        task.assert_matches(key)

        with self._state_lock.locked():
            current = self._writable_document()
            updated = current.with_task(key, task)
            self._write(updated)
            return task

    def remove(self, task_key: str) -> TaskState:
        """Remove one task and return the resulting validated state."""
        key = TaskKey.parse(task_key)

        with self._state_lock.locked():
            current = self._writable_document()
            updated = current.without_task(key)
            self._write(updated)
            return updated
