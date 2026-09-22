# Codex Session Mapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist exact Codex session bindings in Herdr task state and safely resume each managed Agent into its own session after restart.

**Architecture:** Version 2 of `herdr-tasks.json` adds persistent-Agent records while Issue Agents retain session IDs in their existing task records. `herdr_task_state` atomically migrates version 1 before a mutation. `herdr_agents` validates an exact binding and local Codex session metadata before `herdr_runtime` starts a fresh or explicitly resumed Agent.

**Tech Stack:** Python 3.14.7, Pydantic 2.12.5, pytest 8.4.2, Ruff 0.14.10, uv, Herdr CLI, Codex CLI.

**Spec:** [2026-09-22-issue-10-session-mapping-design.md](../specs/2026-09-22-issue-10-session-mapping-design.md)

## Global Constraints

- Keep one state file at the existing Herdr task-state path; do not add a session-mapping file.
- Version 2 requires an empty-or-populated `persistent_agents` map; valid version 1 documents migrate atomically on their first mutation.
- Never use `codex resume --last --all`; resume only a stored exact session ID.
- Session IDs are unique across Issue and persistent Agents and bind repository, Workspace, worktree, branch, and Pane.
- Use the mise-managed Python and uv workflow. Keep shell bootstrap as thin orchestration.
- Do not emit credentials, tokens, raw Codex transcript content, or raw failed subprocess output.
- Use conventional commits with the `Generated-by: Codex` trailer.

## Review Focus

- A valid v1 document migrates without losing unrelated tasks or unknown top-level fields.
- A duplicate session ID across an Issue Agent and a persistent Agent fails before any state write.
- An absent or malformed local session record triggers exactly one fresh start in the intended Pane.
- A usable mapped session whose Herdr startup fails for another reason does not trigger a second Agent.
- A live Agent with a different reported session only updates state after exact binding and uniqueness checks.

---

## File structure

| File | Responsibility |
| --- | --- |
| `tools/herdr_task_state/src/herdr_task_state/model.py` | V1/V2 models, persistent mapping model, migration, global invariants. |
| `tools/herdr_task_state/src/herdr_task_state/store.py` | Locked migration and exact-name mapping operations. |
| `tools/herdr_task_state/src/herdr_task_state/cli.py` | Read-only session list and exact session removal. |
| `tools/herdr_runtime/src/herdr_runtime/models.py` | Herdr-reported Codex session identity. |
| `tools/herdr_runtime/src/herdr_runtime/clients/agent.py` | Decode session identity and pass native resume arguments. |
| `tools/herdr_agents/src/herdr_agents/codex_sessions.py` | Read-only exact-ID index and rollout inspection. |
| `tools/herdr_agents/src/herdr_agents/bindings.py` | Derive persistent Agent repository and branch identity from Git. |
| `tools/herdr_agents/src/herdr_agents/service.py` | Exact live/resume/fresh decision and state update. |
| `tools/herdr_agents/src/herdr_agents/persistent/reconciler.py` | Persistent binding construction and independent recovery. |
| `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/commands/start/implementer.py` | Issue binding and first-prompt policy. |
| `docs/HERDR-TASK-STATE.md`, `docs/HERDR-TASK-LIFECYCLE.md` | Operator contract. |

### Task 1: Add version 2 models and atomic migration

**Files:**

- Modify: `tools/herdr_task_state/src/herdr_task_state/model.py`
- Modify: `tools/herdr_task_state/src/herdr_task_state/store.py`
- Modify: `tools/herdr_task_state/src/herdr_task_state/__init__.py`
- Test: `tools/herdr_task_state/tests/test_herdr_task_state.py`
- Create: `tools/herdr_task_state/tests/test_store.py`

**Interfaces:**

- Produces `PersistentAgentReference`, `Version1TaskState`, version-2 `TaskState`, and `migrate_state(document) -> TaskState`.
- `StateStore.read()` accepts v1 and v2 read-only; `put()` and `remove()` migrate v1 while holding the current lock.

- [ ] **Step 1: Write failing schema tests**

~~~python
def test_v2_requires_persistent_agents() -> None:
    with pytest.raises(StateValidationError, match="persistent_agents"):
        TaskState.parse('{"version":2,"tasks":{}}')

def test_rejects_session_owned_by_issue_and_persistent_agent() -> None:
    with pytest.raises(StateValidationError, match="session ID"):
        TaskState.parse(duplicate_session_document)
~~~

- [ ] **Step 2: Run the failing schema tests**

Run: `uv run --directory tools/herdr_task_state pytest tests/test_herdr_task_state.py -q`

Expected: FAIL because version 2 and global ownership validation do not exist.

- [ ] **Step 3: Implement explicit v1 and v2 models**

~~~python
class PersistentAgentReference(Model):
    codex_session_id: NonEmptyString
    repository: RepositoryName
    workspace_id: NonEmptyString
    workspace_label: NonEmptyString
    worktree: AbsolutePath
    branch: NonEmptyString
    pane_id: NonEmptyString

class TaskState(Model):
    version: Literal[2]
    tasks: dict[str, Task]
    persistent_agents: dict[NonEmptyString, PersistentAgentReference]

def migrate_state(document: Version1TaskState | TaskState) -> TaskState:
    if isinstance(document, TaskState):
        return document
    return TaskState(version=2, tasks=document.tasks, persistent_agents={})
~~~

Validate all task Agent names and session IDs with `persistent_agents` in one model validator. Preserve unknown fields when converting the Pydantic model.

- [ ] **Step 4: Write failing atomic-migration tests**

~~~python
def test_put_migrates_v1_and_preserves_unknown_fields(tmp_path: Path) -> None:
    path = write_v1_state(tmp_path, extra={"future_metadata": {"keep": True}})
    StateStore(path).put(TASK_KEY, replacement_task)
    document = json.loads(path.read_text())
    assert document["version"] == 2
    assert document["persistent_agents"] == {}
    assert document["future_metadata"] == {"keep": True}

def test_failed_migration_preserves_original_bytes(tmp_path: Path) -> None:
    path = write_invalid_v1_state(tmp_path)
    before = path.read_bytes()
    with pytest.raises(StateValidationError):
        StateStore(path).put(TASK_KEY, replacement_task)
    assert path.read_bytes() == before
~~~

- [ ] **Step 5: Run store tests and confirm failure**

Run: `uv run --directory tools/herdr_task_state pytest tests/test_store.py -q`

Expected: FAIL because mutation supports only version 1.

- [ ] **Step 6: Make mutations acquire a writable v2 document**

~~~python
def _writable_document(self) -> TaskState:
    current = self._read() if self.path.exists() or self.path.is_symlink() else TaskState(
        version=2, tasks={}, persistent_agents={}
    )
    migrated = migrate_state(current)
    if migrated is not current:
        self._write(migrated)
    return migrated
~~~

Call this only inside the existing exclusive lock. Keep read-only validation non-mutating. Validate before migration and after conversion; a failure must not replace the source file.

- [ ] **Step 7: Verify Task 1 and commit**

Run: `uv run --directory tools/herdr_task_state pytest -q && uv run --directory tools/herdr_task_state ruff check .`

Expected: PASS.

~~~bash
git add tools/herdr_task_state
git commit -m "feat: migrate task state to version two" -m "Generated-by: Codex"
~~~

### Task 2: Add exact-name session mapping operations and CLI

**Files:**

- Create: `tools/herdr_task_state/src/herdr_task_state/sessions.py`
- Modify: `tools/herdr_task_state/src/herdr_task_state/store.py`
- Modify: `tools/herdr_task_state/src/herdr_task_state/cli.py`
- Modify: `tools/herdr_task_state/src/herdr_task_state/__init__.py`
- Test: `tools/herdr_task_state/tests/test_sessions.py`
- Modify: `tools/herdr_task_state/tests/test_herdr_task_state_cli.py`

**Interfaces:**

~~~python
@dataclass(frozen=True)
class AgentBinding:
    name: str
    repository: str
    workspace_id: str
    workspace_label: str
    worktree: Path
    branch: str
    pane_id: str

class StateStore:
    def find_session(self, name: str) -> SessionMapping | None: ...
    def record_session(self, binding: AgentBinding, session_id: str) -> SessionMapping: ...
    def clear_session(self, name: str) -> None: ...
~~~

- [ ] **Step 1: Write failing exact-target tests**

~~~python
def test_issue_session_update_leaves_another_agent_unchanged(tmp_path: Path) -> None:
    store = StateStore(state_path_with_two_tasks(tmp_path))
    store.record_session(issue_binding, "session-a")
    assert store.find_session("other-agent").session_id == "session-b"

def test_clear_persistent_mapping_keeps_tasks(tmp_path: Path) -> None:
    store = StateStore(state_path_with_persistent_agent(tmp_path))
    store.clear_session("codex-coordinator")
    assert store.find_session("codex-coordinator") is None
    assert store.get(TASK_KEY).issue_number == 10
~~~

- [ ] **Step 2: Run focused mapping tests**

Run: `uv run --directory tools/herdr_task_state pytest tests/test_sessions.py -q`

Expected: FAIL because mapping operations do not exist.

- [ ] **Step 3: Implement state mapping operations**

Search task Agents first by exact name and derive their binding from surrounding task/workstream fields. Reject binding mismatch. If no Issue Agent matches, update or clear only the same-name persistent entry. Revalidate the whole document and retain all unrelated entries before each atomic write.

- [ ] **Step 4: Write failing CLI tests**

~~~python
def test_session_list_is_read_only(cli_env: dict[str, str], capsys: CaptureFixture[str]) -> None:
    before = Path(cli_env["HERDR_TASK_STATE_FILE"]).read_bytes()
    assert main(["session", "list"]) == 0
    assert Path(cli_env["HERDR_TASK_STATE_FILE"]).read_bytes() == before

def test_session_remove_uses_exact_name(cli_env: dict[str, str]) -> None:
    assert main(["session", "remove", "codex-coordinator"]) == 0
    assert StateStore(Path(cli_env["HERDR_TASK_STATE_FILE"])).find_session("other-agent") is not None
~~~

- [ ] **Step 5: Implement nested CLI commands**

Add `herdr-task-state session list` and `herdr-task-state session remove AGENT_NAME`. List does not migrate version 1. Remove validates a non-empty exact name, migrates only if it mutates, prints the new document, and returns exit code 3 for an absent mapping.

- [ ] **Step 6: Verify Task 2 and commit**

Run: `uv run --directory tools/herdr_task_state pytest -q && uv run --directory tools/herdr_task_state ruff check .`

Expected: PASS.

~~~bash
git add tools/herdr_task_state
git commit -m "feat: manage exact Codex session mappings" -m "Generated-by: Codex"
~~~

### Task 3: Expose Herdr session identity and explicit start arguments

**Files:**

- Modify: `tools/herdr_runtime/src/herdr_runtime/models.py`
- Modify: `tools/herdr_runtime/src/herdr_runtime/clients/agent.py`
- Modify: `tools/herdr_runtime/src/herdr_runtime/__init__.py`
- Modify: `tools/herdr_runtime/tests/test_client.py`
- Modify: `tools/herdr_runtime/tests/test_decoding.py`

**Interfaces:**

~~~python
@dataclass(frozen=True)
class AgentInfo:
    name: str
    kind: str
    pane_id: str
    workspace_id: str
    cwd: Path
    codex_session_id: str | None = None

def start(
    self, name: str, pane_id: str, kind: str = "codex", native_args: Sequence[str] = ()
) -> AgentInfo: ...
~~~

- [ ] **Step 1: Write failing runtime tests**

~~~python
def test_agent_decodes_codex_session_id() -> None:
    agent = HerdrClient(runner_with_agent_session("session-a")).agent.find("codex-main")
    assert agent is not None
    assert agent.codex_session_id == "session-a"

def test_start_passes_exact_resume_id() -> None:
    HerdrClient(runner).agent.start("codex-main", "w1:p1", native_args=("resume", "session-a"))
    assert runner.calls[-1][-3:] == ("--", "resume", "session-a")
~~~

- [ ] **Step 2: Run runtime tests**

Run: `uv run --directory tools/herdr_runtime pytest tests/test_client.py tests/test_decoding.py -q`

Expected: FAIL because the current client discards `agent_session` and native arguments.

- [ ] **Step 3: Implement typed decode and explicit argument forwarding**

Accept an absent `agent_session` as `None`. For a present value require an object with `agent == "codex"`, `kind == "id"`, and non-empty `value`; otherwise raise `HerdrError`. Append `("--", *native_args)` only when native arguments are supplied and retain existing start-response identity checks.

- [ ] **Step 4: Verify Task 3 and commit**

Run: `uv run --directory tools/herdr_runtime pytest -q && uv run --directory tools/herdr_runtime ruff check .`

Expected: PASS.

~~~bash
git add tools/herdr_runtime
git commit -m "feat: expose Herdr Codex session identity" -m "Generated-by: Codex"
~~~

### Task 4: Make Agent reconciliation session-aware

**Files:**

- Create: `tools/herdr_agents/src/herdr_agents/codex_sessions.py`
- Create: `tools/herdr_agents/src/herdr_agents/bindings.py`
- Modify: `tools/herdr_agents/src/herdr_agents/service.py`
- Modify: `tools/herdr_agents/src/herdr_agents/persistent/reconciler.py`
- Modify: `tools/herdr_agents/src/herdr_agents/persistent/cli.py`
- Modify: `tools/herdr_agents/pyproject.toml`
- Modify: `tools/herdr_agents/uv.lock`
- Test: `tools/herdr_agents/tests/test_codex_sessions.py`
- Modify: `tools/herdr_agents/tests/test_service.py`
- Modify: `tools/herdr_agents/tests/persistent/test_reconciler.py`

**Interfaces:**

~~~python
class CodexSessionInspector(Protocol):
    def is_usable(self, session_id: str) -> bool: ...

@dataclass(frozen=True)
class EnsuredAgent:
    agent: AgentInfo
    disposition: Literal["live", "resumed", "fresh"]
~~~

- [ ] **Step 1: Write failing stale-session inspector tests**

~~~python
def test_indexed_session_without_rollout_is_not_usable(tmp_path: Path) -> None:
    inspector = CodexSessionFiles(index_path=write_index(tmp_path, "session-a"))
    assert inspector.is_usable("session-a") is False

def test_malformed_index_or_rollout_is_not_usable(tmp_path: Path) -> None:
    assert CodexSessionFiles(write_malformed_index(tmp_path)).is_usable("session-a") is False
~~~

- [ ] **Step 2: Run inspector tests**

Run: `uv run --directory tools/herdr_agents pytest tests/test_codex_sessions.py -q`

Expected: FAIL because no exact-ID session inspector exists.

- [ ] **Step 3: Implement read-only exact-ID inspection**

Read JSON Lines with the standard library. Require a matching index object with non-empty `id`; locate only a regular non-symlink rollout file ending in `-<session-id>.jsonl` below the sibling Codex sessions directory; require UTF-8 JSONL with at least one valid JSON object. Missing, malformed, inaccessible, duplicate, and unsafe files return `False` without logging contents.

- [ ] **Step 4: Write failing AgentManager policy tests**

~~~python
def test_absent_agent_resumes_exact_usable_mapping() -> None:
    result = manager.ensure(target_with_mapping("session-a"))
    assert result.disposition == "resumed"
    assert herdr.start_arguments == ("resume", "session-a")

def test_unusable_mapping_clears_then_starts_fresh_once() -> None:
    result = manager.ensure(target_with_mapping("missing"))
    assert result.disposition == "fresh"
    assert state.cleared == ["codex-issue-10"]

def test_resume_failure_with_usable_mapping_never_starts_fresh() -> None:
    with pytest.raises(AgentManagementError, match="resume"):
        manager.ensure(target_with_mapping("session-a"))
    assert herdr.fresh_start_count == 0
~~~

- [ ] **Step 5: Run AgentManager tests**

Run: `uv run --directory tools/herdr_agents pytest tests/test_service.py -q`

Expected: FAIL because AgentManager has no state, session inspection, or disposition.

- [ ] **Step 6: Implement exact-name policy**

Expand `AgentTarget` with `workspace_label`, `repository`, and `branch`. A live Agent must match placement and report a session ID before it updates state. An absent Agent with no mapping starts fresh. An absent Agent with a non-usable mapped session clears only that mapping and starts fresh once. An absent Agent with a usable mapping starts with `("resume", session_id)`; if that call fails, re-read only the exact name and accept it only if it is live, bound correctly, and reports the same ID. Otherwise raise without fallback.

- [ ] **Step 7: Bind persistent Agents from Git identity**

Use a `CommandRunner` for `git -C CWD remote get-url origin` and `git -C CWD symbolic-ref --quiet --short HEAD`, normalize the origin with the existing repository helper, and combine it with the resolved Pane and definition Workspace label. Reject invalid Git identity before `ensure`. Add `herdr-task-state` as a local dependency in `pyproject.toml` and regenerate only `tools/herdr_agents/uv.lock`.

- [ ] **Step 8: Verify Task 4 and commit**

Run: `uv run --directory tools/herdr_agents pytest -q && uv run --directory tools/herdr_agents ruff check .`

Expected: PASS.

~~~bash
git add tools/herdr_agents
git commit -m "feat: resume managed Codex sessions exactly" -m "Generated-by: Codex"
~~~

### Task 5: Integrate Issue lifecycle, document behavior, and validate reboot restoration

**Files:**

- Modify: `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/commands/start/command.py`
- Modify: `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/commands/start/implementer.py`
- Modify: `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/commands/start/service.py`
- Modify: `tools/herdr_task_lifecycle/pyproject.toml`
- Modify: `tools/herdr_task_lifecycle/uv.lock`
- Modify: `tools/herdr_task_lifecycle/tests/commands/start/test_implementer.py`
- Modify: `tools/herdr_task_lifecycle/tests/commands/start/test_service.py`
- Create: `tools/herdr_agents/tests/integration/test_restart.py`
- Modify: `docs/HERDR-TASK-STATE.md`
- Modify: `docs/HERDR-TASK-LIFECYCLE.md`

**Interfaces:**

- Consumes `EnsuredAgent.disposition` and `AgentInfo.codex_session_id`.
- Produces `AgentReference(name=..., codex_session_id=...)`.

- [ ] **Step 1: Write failing Issue Agent tests**

~~~python
def test_fresh_implementer_records_session_and_prompts() -> None:
    reference = TaskAgentStarter(manager).ensure_implementer(key, task, "w16:p2")
    assert reference == AgentReference(name=task_agent_name(key), codex_session_id="session-a")
    assert len(manager.prompts) == 1

def test_resumed_implementer_does_not_receive_duplicate_prompt() -> None:
    reference = TaskAgentStarter(resumed_manager).ensure_implementer(key, stored_task, "w16:p2")
    assert reference.codex_session_id == "session-a"
    assert resumed_manager.prompts == []
~~~

- [ ] **Step 2: Run focused lifecycle tests**

Run: `uv run --directory tools/herdr_task_lifecycle pytest tests/commands/start/test_implementer.py -q`

Expected: FAIL because Issue startup currently discards observed IDs and does not distinguish fresh from resumed startup.

- [ ] **Step 3: Preserve session and create full Issue binding**

Construct `AgentTarget` from task key, `task.herdr`, main worktree, branch, and Pane. Require `result.agent.codex_session_id`; return it in `AgentReference`. Send the initial Issue prompt only for `disposition == "fresh"`. Initialize a new lifecycle state as `TaskState(version=2, tasks={}, persistent_agents={})`.

- [ ] **Step 4: Add migration coverage**

~~~python
def test_start_migrates_v1_before_recording_agent(tmp_path: Path) -> None:
    TaskStarter(v1_state_path, runner=fake_runner, herdr=fake_herdr, agent_starter=fake_starter).start(10, worktree)
    assert json.loads(v1_state_path.read_text())["version"] == 2
~~~

Run: `uv run --directory tools/herdr_task_lifecycle pytest -q && uv run --directory tools/herdr_task_lifecycle ruff check .`

Expected: PASS.

- [ ] **Step 5: Add isolated reboot integration coverage**

Create an integration test guarded by `HERDR_INTEGRATION=1`. It starts a named non-default Herdr session and temporary state, registers two Agents in distinct temporary Git worktrees, captures distinct IDs, stops only that test server, runs bootstrap reconciliation, and asserts each exact Agent name, Pane, worktree, and ID match its record. A second case changes one binding and asserts no wrong-project resume. Teardown targets only the named test session.

- [ ] **Step 6: Update operator documentation**

Document v2, automatic first-mutation migration, persistent mappings, nested Issue IDs, unique ownership, exact session commands, safe fallback, stale conflicts, and Issue cleanup removing its nested mapping. Mark lifecycle session recovery implemented only after the verification below passes.

- [ ] **Step 7: Run all verification**

~~~bash
uv run --directory tools/herdr_runtime pytest -q
uv run --directory tools/herdr_agents pytest -q
uv run --directory tools/herdr_task_state pytest -q
uv run --directory tools/herdr_task_lifecycle pytest -q
uv run --directory tools/herdr_runtime ruff check .
uv run --directory tools/herdr_agents ruff check .
uv run --directory tools/herdr_task_state ruff check .
uv run --directory tools/herdr_task_lifecycle ruff check .
HERDR_INTEGRATION=1 uv run --directory tools/herdr_agents pytest tests/integration/test_restart.py -q
~~~

Expected: all unit suites and lint pass; integration proves exact multi-Agent restoration without touching the active Herdr session.

- [ ] **Step 8: Commit lifecycle integration and documentation**

~~~bash
git add tools/herdr_task_lifecycle tools/herdr_agents/tests/integration docs/HERDR-TASK-STATE.md docs/HERDR-TASK-LIFECYCLE.md
git commit -m "feat: restore Codex sessions by managed binding" -m "Generated-by: Codex"
~~~
