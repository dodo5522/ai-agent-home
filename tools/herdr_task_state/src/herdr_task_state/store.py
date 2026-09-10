"""Filesystem-backed, locked Herdr task-state storage."""

import fcntl
import os
import stat
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from .model import (
    StateValidationError,
    Task,
    TaskKey,
    TaskState,
)


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
        return TaskState(version=1, tasks={})

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

    def put(self, task_key: str, task: Task) -> Task:
        """Validate and atomically store one task under its stable key."""
        key = TaskKey.parse(task_key)
        task.assert_matches(key)

        with self._state_lock.locked():
            current = (
                self._read() if self.path.exists() or self.path.is_symlink() else self._empty()
            )
            updated = current.with_task(key, task)
            self._write(updated)
            return task

    def remove(self, task_key: str) -> TaskState:
        """Remove one task and return the resulting validated state."""
        key = TaskKey.parse(task_key)

        with self._state_lock.locked():
            if not self.path.exists() and not self.path.is_symlink():
                empty = self._empty()
                self._write(empty)
                return empty
            current = self._read()
            updated = current.without_task(key)
            if updated is not current:
                self._write(updated)
            return updated
