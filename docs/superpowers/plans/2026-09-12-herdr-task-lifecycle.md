# Herdr Task Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the canonical `herdr-task` CLI with safe Issue start and resumable cleanup workflows.

**Architecture:** Replace the standalone task-start package with `herdr_task_lifecycle`. Shared GitHub, state, subprocess, and Herdr adapters stay at the package root; `commands/start` and `commands/cleanup` own command-specific logic. Cleanup plans are deterministic, validate stored IDs against live resources, and persist completed actions after every step so retries cannot target unmanaged resources.

**Tech Stack:** Python 3.14 through mise and uv; Pydantic 2.12.5; pytest 8.4.2; Ruff 0.14.10; Bash wrappers; Git and Herdr CLI JSON APIs.

**Spec:** `docs/superpowers/specs/2026-09-12-herdr-task-lifecycle-design.md`

## Global Constraints

- Use `/home/takashi/.local/share/mise/shims/uv` through thin Bash wrappers; do not put lifecycle logic in Bash.
- Do not add dependencies beyond the existing local `herdr-task-state` dependency.
- Use `GH_TOKEN` only in the subprocess environment for `gh` commands; never serialize, log, or include token values in errors.
- Mutate only state-recorded resource IDs after live identity validation; never infer managed ownership from labels.
- `cleanup --plan` is read-only. `cleanup --execute` needs an exact confirmed task root and must never delete a repository workspace or repository Space.
- Keep all subcommand-specific Python modules in `commands/<subcommand>/`; top-level modules are shared only.
- Write a failing pytest before each production behavior change, run it red, then write the minimal implementation and run it green.
- Every commit uses a conventional subject, explanatory body, blank line, and `Generated-by: Codex` trailer.

---

### Task 1: Create the lifecycle package and canonical CLI shell

**Files:**
- Create: `tools/herdr_task_lifecycle/pyproject.toml`
- Create: `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/__init__.py`
- Create: `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/cli.py`
- Create: `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/errors.py`
- Create: `tools/herdr_task_lifecycle/tests/test_cli.py`
- Create: `bin/herdr-task`

**Interfaces:**
- Produces `main(argv: Sequence[str] | None = None) -> int` as the `herdr-task` console entrypoint.
- Produces `LifecycleError(message: str)` and `ExitCode` for stable user-facing failures.
- Later tasks register `add_parser(subparsers: argparse._SubParsersAction) -> None` from `commands.start.command` and `commands.cleanup.command`.

- [ ] **Step 1: Write the failing CLI tests**

```python
def test_root_help_lists_start_and_cleanup(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--help"]) == 0
    assert "start" in capsys.readouterr().out
    assert "cleanup" in capsys.readouterr().out


def test_unknown_subcommand_is_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["unknown"]) == 2
    assert "invalid choice" in capsys.readouterr().err
```

- [ ] **Step 2: Run the tests to verify red**

Run: `uv run --project tools/herdr_task_lifecycle --group dev pytest tools/herdr_task_lifecycle/tests/test_cli.py -v`

Expected: FAIL because the project and `main` entrypoint do not exist.

- [ ] **Step 3: Create the minimal project and root parser**

Define `pyproject.toml` with exact package name `herdr-task`, Python `>=3.14`, local source dependency `herdr-task-state = { path = "../herdr_task_state" }`, and pinned pytest/Ruff development dependencies matching existing tools. In `cli.py`, create an argparse parser with required subparsers and temporary registered command handlers. Return `0` for help and `2` for parser usage errors; print `LifecycleError` messages to stderr without tracebacks.

- [ ] **Step 4: Add the thin wrapper**

Create `bin/herdr-task` following `bin/herdr-task-state`: resolve its own directory, select `${UV_BIN:-/home/takashi/.local/share/mise/shims/uv}`, and `exec` `uv run --project "$SCRIPT_DIR/../tools/herdr_task_lifecycle" herdr-task "$@"`.

- [ ] **Step 5: Run the tests to verify green**

Run: `uv run --project tools/herdr_task_lifecycle --group dev pytest tools/herdr_task_lifecycle/tests/test_cli.py -v`

Expected: PASS with root help listing both canonical subcommands.

- [ ] **Step 6: Commit the package shell**

```bash
git add tools/herdr_task_lifecycle bin/herdr-task
git commit -m $'feat: add Herdr task lifecycle CLI\n\nEstablish the canonical command package and shared command boundary.\n\nGenerated-by: Codex'
```

### Task 2: Extend typed task state for resumable cleanup

**Files:**
- Modify: `tools/herdr_task_state/src/herdr_task_state/model.py`
- Modify: `tools/herdr_task_state/tests/test_herdr_task_state.py`
- Modify: `docs/HERDR-TASK-STATE.md`

**Interfaces:**
- Produces `CleanupProgress` with `task_root: AbsolutePath`, `phase: Literal["pending", "partial"]`, and `completed_actions: set[CleanupAction]` serialized deterministically.
- Adds optional `cleanup: CleanupProgress` to `Task`; absence continues to mean active, not-cleaning state.
- `TaskState.with_task()` and `StateStore.put()` continue to atomically store the extended model.

- [ ] **Step 1: Write failing state-model tests**

```python
def test_task_accepts_pending_cleanup_progress() -> None:
    task = Task.parse(
        "dodo5522/ai-agent-home#33",
        json.dumps({
            "repository": "dodo5522/ai-agent-home",
            "issue_number": 33,
            "workstreams": {"main": {}},
            "cleanup": {
                "task_root": "/home/takashi/work/tasks/issue-33",
                "phase": "pending",
                "completed_actions": [],
            },
        }),
    )
    assert task.cleanup is not None
    assert task.cleanup.completed_actions == set()


def test_task_rejects_unknown_cleanup_action() -> None:
    with pytest.raises(StateValidationError, match="cleanup"):
        Task.parse("dodo5522/ai-agent-home#33", payload_with_cleanup_action("erase-home"))
```

- [ ] **Step 2: Run the focused tests to verify red**

Run: `uv run --project tools/herdr_task_state --group dev pytest tools/herdr_task_state/tests/test_herdr_task_state.py -k cleanup -v`

Expected: FAIL because `Task` has no typed `cleanup` field.

- [ ] **Step 3: Implement the optional cleanup model**

Add a strict `CleanupProgress` Pydantic model and a closed action vocabulary: `tab`, `worktree`, and `task_root`. Reject nulls, duplicate actions, unknown action values, non-absolute roots, and `partial` records with no completed action. Add the optional field to `Task`, export the model, and preserve backward compatibility for existing state files that omit it.

- [ ] **Step 4: Update the state reference**

Document the cleanup object as an optional runtime record, its valid phases and completed action values, and the rule that it is deleted with the task only after lifecycle cleanup has completed. Link lifecycle behavior to `HERDR-TASK-LIFECYCLE.md` rather than duplicating cleanup procedure.

- [ ] **Step 5: Run state tests and lint to verify green**

Run:

```bash
uv run --project tools/herdr_task_state --group dev pytest tools/herdr_task_state/tests -v
uv run --project tools/herdr_task_state --group dev ruff format --check tools/herdr_task_state/src tools/herdr_task_state/tests
uv run --project tools/herdr_task_state --group dev ruff check tools/herdr_task_state/src tools/herdr_task_state/tests
```

Expected: all state tests and Ruff checks pass.

- [ ] **Step 6: Commit the cleanup state record**

```bash
git add tools/herdr_task_state docs/HERDR-TASK-STATE.md
git commit -m $'feat: track resumable task cleanup\n\nAdd typed cleanup progress to the validated task state schema.\n\nGenerated-by: Codex'
```

### Task 3: Migrate shared start dependencies and the start command

**Files:**
- Create: `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/runner.py`
- Create: `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/herdr.py`
- Create: `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/identity.py`
- Create: `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/state.py`
- Create: `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/commands/__init__.py`
- Create: `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/commands/start/__init__.py`
- Create: `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/commands/start/command.py`
- Create: `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/commands/start/service.py`
- Create: `tools/herdr_task_lifecycle/tests/commands/start/test_service.py`
- Modify: `tools/herdr_task_lifecycle/tests/test_cli.py`

**Interfaces:**
- Produces `TaskStarter.start(issue_number: int, cwd: Path) -> TaskStartResolution`.
- Produces `commands.start.command.add_parser(subparsers)` that dispatches `herdr-task start`.
- `identity.load_issue_title()` calls `gh issue view` with `GH_TOKEN` set to the ephemeral GitHub App token from `bin/get-github-app-token.py` when no caller token exists.

- [ ] **Step 1: Copy and adapt start tests before moving production code**

Move the fake runner, fake Herdr implementation, and behavioral tests from `tools/herdr_task_start/tests/test_herdr_task_start.py` into the start command test directory. Update command expectations from `herdr-task-start 32` to `herdr-task start 32`, and add:

```python
def test_issue_lookup_uses_github_app_token_without_echoing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = RecordingRunner(token="test-installation-token")
    runner.respond_to_issue_lookup(returncode=1, stderr="authentication failed")
    with pytest.raises(LifecycleError, match="cannot load GitHub Issue title") as error:
        load_issue_title("dodo5522/ai-agent-home", 33, runner)
    assert runner.gh_environment["GH_TOKEN"] == "test-installation-token"
    assert "test-installation-token" not in str(error.value)
```

- [ ] **Step 2: Run the migrated start tests to verify red**

Run: `uv run --project tools/herdr_task_lifecycle --group dev pytest tools/herdr_task_lifecycle/tests/commands/start -v`

Expected: FAIL because the lifecycle start modules are not implemented.

- [ ] **Step 3: Move shared adapters and start service**

Move the existing task-start implementation into the specified shared and `commands/start` modules without changing reconciliation behavior. Change imports to use `herdr_task_state`. Preserve Herdr `--no-focus`, root-Pane validation, stale-ID behavior, and rollback semantics. Extend `CommandRunner.run()` with an optional environment mapping, then supply the token from `bin/get-github-app-token.py` through a copied environment dictionary only when `GH_TOKEN` is absent; never add it to command arguments or errors.

- [ ] **Step 4: Register and implement `start` parsing**

Register `start` at the root parser. It accepts one positive Issue number and optional `--cwd`, invokes `TaskStarter`, and emits the same structured JSON resolution currently returned by task-start. Convert expected state, Herdr, Git, and GitHub failures into stable stderr diagnostics.

- [ ] **Step 5: Run start tests and lint to verify green**

Run:

```bash
uv run --project tools/herdr_task_lifecycle --group dev pytest tools/herdr_task_lifecycle/tests/commands/start tools/herdr_task_lifecycle/tests/test_cli.py -v
uv run --project tools/herdr_task_lifecycle --group dev ruff format --check tools/herdr_task_lifecycle/src tools/herdr_task_lifecycle/tests
uv run --project tools/herdr_task_lifecycle --group dev ruff check tools/herdr_task_lifecycle/src tools/herdr_task_lifecycle/tests
```

Expected: migrated start tests pass and only shared modules remain at package root.

- [ ] **Step 6: Commit the migrated start workflow**

```bash
git add tools/herdr_task_lifecycle
git commit -m $'feat: move task start into lifecycle CLI\n\nExpose the existing safe start workflow as herdr-task start.\n\nGenerated-by: Codex'
```

### Task 4: Build read-only cleanup planning and safety validation

**Files:**
- Create: `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/commands/cleanup/__init__.py`
- Create: `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/commands/cleanup/planner.py`
- Create: `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/commands/cleanup/command.py`
- Create: `tools/herdr_task_lifecycle/tests/commands/cleanup/test_planner.py`
- Modify: `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/herdr.py`
- Modify: `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/state.py`

**Interfaces:**
- Produces immutable `CleanupActionPlan(action: Literal["tab", "worktree", "task_root"], outcome: Literal["delete", "already_absent", "blocked"], target: str, reason: str)`.
- Produces `CleanupPlan(task_key: TaskKey, task_root: Path | None, actions: tuple[CleanupActionPlan, CleanupActionPlan, CleanupActionPlan])` and `CleanupPlanner.plan(task_key: TaskKey) -> CleanupPlan`.
- Produces `commands.cleanup.command.add_parser(subparsers)` accepting exclusive `--plan` or `--execute` and `--confirm-task-root`.

- [ ] **Step 1: Write failing planner tests**

```python
def test_plan_only_targets_stored_managed_resources(cleanup_fixture: CleanupFixture) -> None:
    plan = cleanup_fixture.planner.plan(cleanup_fixture.task_key)
    assert [item.action for item in plan.actions] == ["tab", "worktree", "task_root"]
    assert {item.outcome for item in plan.actions} == {"delete"}
    assert cleanup_fixture.herdr.close_calls == []


def test_plan_blocks_task_root_outside_tasks_directory(cleanup_fixture: CleanupFixture) -> None:
    cleanup_fixture.set_task_root(Path("/tmp/issue-33"))
    plan = cleanup_fixture.planner.plan(cleanup_fixture.task_key)
    assert plan.actions[-1].outcome == "blocked"


def test_plan_does_not_import_label_matched_unmanaged_tab(cleanup_fixture: CleanupFixture) -> None:
    cleanup_fixture.remove_stored_tab_id()
    cleanup_fixture.herdr.add_tab_with_matching_label()
    assert cleanup_fixture.planner.plan(cleanup_fixture.task_key).actions[0].outcome == "blocked"
```

- [ ] **Step 2: Run planner tests to verify red**

Run: `uv run --project tools/herdr_task_lifecycle --group dev pytest tools/herdr_task_lifecycle/tests/commands/cleanup/test_planner.py -v`

Expected: FAIL because cleanup planning does not exist.

- [ ] **Step 3: Implement plan models and live validation**

Implement planner-only reads. Validate stored Tab ID, workspace ID, and label by live Herdr lookup; report missing managed resources as `already_absent` and mismatch as `blocked`. Use `git worktree list --porcelain` to require a stored path to be a non-primary registered worktree. Find the candidate task root by walking parents from every stored worktree to the direct `.codex-task-root` marker, then enforce the exact `/home/takashi/work/tasks/` boundary and verify there are no other registered worktrees below it. Never create, close, remove, rename, or write state in this task.

- [ ] **Step 4: Wire `cleanup --plan` and reject unsafe invocation shapes**

The command prints normalized JSON plan output for `--plan`. Reject `--execute` without `--confirm-task-root`, reject a confirmation that is not absolute, and reject both mode flags together as a usage error. Keep `--execute` temporarily unimplemented with an explicit command error until Task 5 supplies the executor.

- [ ] **Step 5: Run planner tests and lint to verify green**

Run:

```bash
uv run --project tools/herdr_task_lifecycle --group dev pytest tools/herdr_task_lifecycle/tests/commands/cleanup/test_planner.py -v
uv run --project tools/herdr_task_lifecycle --group dev ruff format --check tools/herdr_task_lifecycle/src tools/herdr_task_lifecycle/tests
uv run --project tools/herdr_task_lifecycle --group dev ruff check tools/herdr_task_lifecycle/src tools/herdr_task_lifecycle/tests
```

Expected: planning is demonstrably read-only and every unsafe target becomes a blocker.

- [ ] **Step 6: Commit the cleanup planner**

```bash
git add tools/herdr_task_lifecycle
git commit -m $'feat: plan safe Herdr task cleanup\n\nAdd read-only validation for managed lifecycle cleanup targets.\n\nGenerated-by: Codex'
```

### Task 5: Execute cleanup with persisted progress and retry support

**Files:**
- Create: `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/commands/cleanup/executor.py`
- Modify: `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/commands/cleanup/command.py`
- Modify: `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/state.py`
- Create: `tools/herdr_task_lifecycle/tests/commands/cleanup/test_executor.py`

**Interfaces:**
- Produces `CleanupExecutor.execute(plan: CleanupPlan, confirmed_task_root: Path) -> CleanupResult`.
- `CleanupResult` contains task key, completed action names, and whether state mapping was removed.
- State adapter exposes `record_cleanup_progress(task_key: TaskKey, progress: CleanupProgress) -> Task` and `remove_task_after_cleanup(task_key: TaskKey) -> None`.

- [ ] **Step 1: Write failing executor tests**

```python
def test_execute_runs_tab_worktree_root_then_removes_state(cleanup_fixture: CleanupFixture) -> None:
    plan = cleanup_fixture.planner.plan(cleanup_fixture.task_key)
    result = cleanup_fixture.executor.execute(plan, cleanup_fixture.task_root)
    assert cleanup_fixture.events == ["tab", "worktree", "task_root", "state"]
    assert result.mapping_removed is True


def test_execute_persists_partial_progress_and_retry_skips_completed_action(
    cleanup_fixture: CleanupFixture,
) -> None:
    cleanup_fixture.fail_on("worktree")
    with pytest.raises(LifecycleError, match="worktree"):
        cleanup_fixture.executor.execute(cleanup_fixture.planner.plan(cleanup_fixture.task_key), cleanup_fixture.task_root)
    assert cleanup_fixture.state().tasks[str(cleanup_fixture.task_key)].cleanup.completed_actions == {"tab"}
    cleanup_fixture.clear_failure()
    cleanup_fixture.executor.execute(cleanup_fixture.planner.plan(cleanup_fixture.task_key), cleanup_fixture.task_root)
    assert cleanup_fixture.events.count("tab") == 1


def test_execute_refuses_different_confirmed_root(cleanup_fixture: CleanupFixture) -> None:
    with pytest.raises(LifecycleError, match="confirm-task-root"):
        cleanup_fixture.executor.execute(cleanup_fixture.planner.plan(cleanup_fixture.task_key), Path("/tmp/other"))
```

- [ ] **Step 2: Run executor tests to verify red**

Run: `uv run --project tools/herdr_task_lifecycle --group dev pytest tools/herdr_task_lifecycle/tests/commands/cleanup/test_executor.py -v`

Expected: FAIL because no executor or persisted progress exists.

- [ ] **Step 3: Implement atomic progress and ordered actions**

Before the first mutation, write `CleanupProgress(phase="pending", completed_actions=set(), task_root=plan.task_root)`. Revalidate the plan immediately before each action, skip completed or already-absent items, and atomically add the action name after a successful action. On any failure, set phase to `partial`, preserve the task mapping, and raise a safe error. Close only validated Tabs; invoke Git worktree removal only for validated non-primary paths; use one `shutil.rmtree()` call only after all task-root checks still pass. After all actions complete, remove the whole task record through `StateStore.remove()`.

- [ ] **Step 4: Wire guarded `cleanup --execute`**

Require the planner to return no `blocked` outcomes, parse `--confirm-task-root` as a resolved absolute `Path`, execute with the service, and emit normalized JSON result. Do not add an implicit confirmation, `--force`, or interactive deletion prompt.

- [ ] **Step 5: Run cleanup tests and lint to verify green**

Run:

```bash
uv run --project tools/herdr_task_lifecycle --group dev pytest tools/herdr_task_lifecycle/tests/commands/cleanup -v
uv run --project tools/herdr_task_lifecycle --group dev ruff format --check tools/herdr_task_lifecycle/src tools/herdr_task_lifecycle/tests
uv run --project tools/herdr_task_lifecycle --group dev ruff check tools/herdr_task_lifecycle/src tools/herdr_task_lifecycle/tests
```

Expected: action order, exact confirmation, safety revalidation, partial failure, and retry all pass.

- [ ] **Step 6: Commit resumable cleanup**

```bash
git add tools/herdr_task_lifecycle
git commit -m $'feat: execute resumable task cleanup\n\nRemove only validated managed resources with persisted retry progress.\n\nGenerated-by: Codex'
```

### Task 6: Consolidate lifecycle documentation and remove superseded start package

**Files:**
- Create: `docs/HERDR-TASK-LIFECYCLE.md`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `docs/HERDR-TASK-STATE.md`
- Delete: `docs/HERDR-TASK-START.md`
- Delete: `bin/herdr-task-start`
- Delete: `tools/herdr_task_start/`

**Interfaces:**
- Documents `herdr-task start`, cleanup plan, cleanup execution, human approval, and retry operations.
- Documents future `pr` and `pane` namespaces only as reserved work; it does not claim they exist.

- [ ] **Step 1: Write documentation assertions as shell tests**

Add a shell check under `tests/herdr_task_lifecycle_test.sh` that fails until the canonical command and source-of-truth links exist:

```bash
rg -q 'herdr-task start' docs/HERDR-TASK-LIFECYCLE.md
rg -q 'HERDR-TASK-LIFECYCLE.md' README.md AGENTS.md docs/HERDR-TASK-STATE.md
test ! -e docs/HERDR-TASK-START.md
test ! -e bin/herdr-task-start
test ! -d tools/herdr_task_start
```

- [ ] **Step 2: Run the documentation test to verify red**

Run: `bash tests/herdr_task_lifecycle_test.sh`

Expected: FAIL because the old package and start document still exist.

- [ ] **Step 3: Write the lifecycle source of truth and update links**

Document role/identifier/label/cwd tables, managed-versus-unmanaged boundaries, start behavior, PR-open/review retention, merge and non-PR cleanup triggers, the exact plan/approval/execute/retry process, and future PR/Pane command boundaries. Replace README's start command examples with `bin/herdr-task start 32`; link AGENTS and state documentation to the new reference without repeating tables.

- [ ] **Step 4: Remove superseded implementation and documentation**

Delete the old start wrapper, package, tests, and single-purpose document only after lifecycle start tests pass. Update any test commands, install references, package sources, and `uv.lock` references that still name the removed package.

- [ ] **Step 5: Run documentation test and full relevant validation**

Run:

```bash
bash tests/herdr_task_lifecycle_test.sh
uv run --project tools/herdr_task_state --group dev pytest tools/herdr_task_state/tests -v
uv run --project tools/herdr_task_lifecycle --group dev pytest tools/herdr_task_lifecycle/tests -v
```

Expected: canonical documentation references only the lifecycle CLI, and all affected Python tests pass.

- [ ] **Step 6: Commit the migration and documentation**

```bash
git add README.md AGENTS.md docs bin tools tests
git commit -m $'docs: consolidate Herdr task lifecycle\n\nMake lifecycle guidance canonical and remove the superseded start command.\n\nGenerated-by: Codex'
```

### Task 7: Run complete verification and prepare the Pull Request

**Files:**
- Modify only if verification exposes a defect: exact relevant file and its focused regression test.

**Interfaces:**
- Confirms `bin/herdr-task` supports `start --help`, `cleanup --help`, and no old `herdr-task-start` command remains.

- [ ] **Step 1: Run the full test suites**

Run:

```bash
uv run --project tools/herdr_task_state --group dev pytest tools/herdr_task_state/tests -v
uv run --project tools/herdr_task_lifecycle --group dev pytest tools/herdr_task_lifecycle/tests -v
bash tests/herdr_task_state_test.sh
bash tests/herdr_task_lifecycle_test.sh
```

Expected: all tests pass with no warnings or unexpected output.

- [ ] **Step 2: Run all affected Ruff checks**

Run:

```bash
uv run --project tools/herdr_task_state --group dev ruff format --check tools/herdr_task_state/src tools/herdr_task_state/tests
uv run --project tools/herdr_task_state --group dev ruff check tools/herdr_task_state/src tools/herdr_task_state/tests
uv run --project tools/herdr_task_lifecycle --group dev ruff format --check tools/herdr_task_lifecycle/src tools/herdr_task_lifecycle/tests
uv run --project tools/herdr_task_lifecycle --group dev ruff check tools/herdr_task_lifecycle/src tools/herdr_task_lifecycle/tests
```

Expected: all formatting and lint checks pass.

- [ ] **Step 3: Smoke-test entrypoints without mutating the live state**

Run:

```bash
bin/herdr-task --help
bin/herdr-task start --help
bin/herdr-task cleanup --help
test ! -e bin/herdr-task-start
```

Expected: every help command exits `0`; the old wrapper is absent.

- [ ] **Step 4: Inspect the final change set**

Run:

```bash
git diff --check origin/main...HEAD
git status --short --branch
git log --oneline origin/main..HEAD
```

Expected: no whitespace errors, clean worktree, and only intended commits.

- [ ] **Step 5: Push and open the Pull Request**

Push `feat/issue-33-task-lifecycle`, create a Pull Request targeting `main`, request review from `dodo5522`, and do not merge it.
