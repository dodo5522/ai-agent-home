# Issue #30 Worktree Registration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `herdr-task start` safely persist an Issue's validated main-workstream Git worktree and branch alongside its Herdr resources.

**Architecture:** A focused Git-worktree resolver proves that the cwd is a non-primary, branch-attached worktree under a marked task root. `TaskStarter` invokes it before Herdr reconciliation, rejects a state conflict before any mutation, and writes its results into the existing atomic state update.

**Tech Stack:** Python 3.14.7, standard library, Pydantic, pytest 8.4.2, Ruff 0.14.10, Git porcelain, Herdr CLI adapter.

**Spec:** `docs/superpowers/specs/2026-09-18-issue-30-work-management-design.md`

## Global Constraints

- Use the mise-managed Python and `uv` commands for `tools/herdr_task_lifecycle`.
- Add no dependency and keep non-trivial logic in Python.
- The worktree must be below `/home/takashi/work/tasks/` and have an ancestor task root with a direct regular `.codex-task-root` marker.
- Validate before any Herdr or state mutation; roll back only Herdr resources created by the failing invocation.
- Never adopt or mutate label-matched unmanaged Herdr or Git resources.
- Use `#<issue-number> <short-title>` for primary Issue Tab labels; preserve the stable `owner/repository#issue-number` state key.
- Do not implement Agent, Codex-session, PR, extra-Pane, parallel-workstream, or Git-worktree creation/removal operations.
- Every commit uses a conventional subject, explanatory body, blank separator, and `Generated-by: Codex` trailer.

## Review Focus

- A primary checkout must fail before a Workspace or state record is created.
- A detached checkout must fail without storing an absent or guessed branch.
- A cwd outside a marked task root must fail before Herdr calls.
- An existing Issue mapped to another worktree or branch must not be overwritten.
- A legacy Issue without worktree metadata must upgrade once while preserving unrelated metadata and workstreams.

---

### Task 1: Validate an existing managed Git worktree

**Files:**

- Create: `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/worktree.py`
- Create: `tools/herdr_task_lifecycle/tests/test_worktree.py`

**Interfaces:**

- Consumes: `CommandRunner.run(arguments, cwd=None, environment=None)` and `CommandResult` from `herdr_task_lifecycle.runner`.
- Produces: `TASK_ROOTS_DIRECTORY = Path("/home/takashi/work/tasks")`.
- Produces: `WorktreeRegistration(path: Path, branch: str, task_root: Path)`.
- Produces: `resolve_managed_worktree(cwd: Path, runner: CommandRunner, task_roots_directory: Path = TASK_ROOTS_DIRECTORY) -> WorktreeRegistration`.

- [ ] **Step 1: Write failing resolver tests**

Name the breaks: accepting a primary checkout, accepting detached HEAD, or accepting a path outside a task root would make cleanup unsafe. Create a fixture with `<tmp>/tasks/issue-30/.codex-task-root` and a `worktree` child plus a controlled `RecordingRunner`.

```python
def test_resolves_registered_branch_worktree_under_marker(worktree_fixture: WorktreeFixture) -> None:
    registration = resolve_managed_worktree(
        worktree_fixture.worktree, worktree_fixture.runner, worktree_fixture.tasks_directory
    )

    assert registration == WorktreeRegistration(
        path=worktree_fixture.worktree,
        branch="feat/issue-30-herdr-work-management",
        task_root=worktree_fixture.task_root,
    )


def test_rejects_primary_checkout(worktree_fixture: WorktreeFixture) -> None:
    worktree_fixture.respond_git_layout(git_dir=".git", git_common_dir=".git", branch="main")

    with pytest.raises(LifecycleError, match="primary worktree"):
        resolve_managed_worktree(
            worktree_fixture.worktree, worktree_fixture.runner, worktree_fixture.tasks_directory
        )


def test_rejects_missing_task_root_marker(worktree_fixture: WorktreeFixture) -> None:
    worktree_fixture.marker.unlink()

    with pytest.raises(LifecycleError, match="task root"):
        resolve_managed_worktree(
            worktree_fixture.worktree, worktree_fixture.runner, worktree_fixture.tasks_directory
        )
```

Also test: nonzero `symbolic-ref` rejects detached HEAD; a porcelain inventory with no matching `worktree` record rejects; a marker outside the passed task-root boundary rejects; and a failing Git command with sentinel stdout/stderr does not leak the sentinel in the error.

- [ ] **Step 2: Run the resolver tests to verify RED**

Run:

```bash
uv run --project tools/herdr_task_lifecycle --group dev pytest tools/herdr_task_lifecycle/tests/test_worktree.py -v
```

Expected: collection fails because the `worktree` module and resolver do not exist.

- [ ] **Step 3: Implement the minimal resolver**

Create `worktree.py`. It must call these literal command forms through the runner, never a shell:

```python
runner.run(["git", "-C", str(cwd), "rev-parse", "--git-dir"])
runner.run(["git", "-C", str(cwd), "rev-parse", "--git-common-dir"])
runner.run(["git", "-C", str(cwd), "symbolic-ref", "--quiet", "--short", "HEAD"])
runner.run(["git", "-C", str(cwd), "worktree", "list", "--porcelain"])
```

Resolve relative Git-directory results against `cwd`; equal directories identify the primary checkout. Treat a nonzero symbolic-ref as detached. Parse blank-line-separated porcelain records, collect only `worktree <path>` lines, and require one path exactly equal to `cwd.resolve()`. Walk `cwd.resolve()` and its parents for the nearest regular marker. Its directory must be strictly below `task_roots_directory.resolve()` and contain the cwd. Every rejection raises a fixed `LifecycleError` message without command output.

- [ ] **Step 4: Run the focused tests to verify GREEN**

Run the Step 2 command again.

Expected: every valid registration and all primary, detached, inventory, marker, boundary, and secret-output cases pass.

- [ ] **Step 5: Commit the resolver**

```bash
git add tools/herdr_task_lifecycle/src/herdr_task_lifecycle/worktree.py tools/herdr_task_lifecycle/tests/test_worktree.py
git commit -m "feat: validate managed task worktrees" -m "Resolve branch-attached non-primary worktrees beneath marked task roots." -m "Generated-by: Codex"
```

### Task 2: Register worktree metadata during startup

**Files:**

- Modify: `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/commands/start/service.py:12-175`
- Modify: `tools/herdr_task_lifecycle/tests/commands/start/test_service.py:1-590`

**Interfaces:**

- Consumes: `resolve_managed_worktree(cwd, self._runner) -> WorktreeRegistration` from Task 1.
- Produces: `TaskStarter.start()` state with `main.worktree == str(registration.path)` and `main.branch == registration.branch`.
- Preserves: unrelated Task metadata, non-main workstreams, `pull_requests`, `agents`, and non-root role Pane IDs.

- [ ] **Step 1: Add failing startup tests**

Extend `StartFixture` with a temporary marked task root, a linked worktree cwd, and default Git runner responses for Task 1's resolver. Replace its old bare `tmp_path` cwd. Add these behavior tests:

```python
def test_first_start_persists_worktree_branch_and_hash_label(start_fixture: StartFixture) -> None:
    result = start_fixture.run(32)
    main = result.task.workstreams["main"]

    assert main.worktree == str(start_fixture.worktree)
    assert main.branch == "feat/issue-32-herdr-task-start"
    assert main.tab_label == "#32 Herdr task-start"


def test_legacy_task_is_upgraded_with_worktree_registration(start_fixture: StartFixture) -> None:
    start_fixture.write_state_with_ids("w9", "w9:t2", "w9:p3")
    start_fixture.make_managed_tab("w9", "w9:t2", "w9:p3", "#32 Herdr task-start")

    result = start_fixture.run(32)

    assert result.task.workstreams["main"].worktree == str(start_fixture.worktree)
    assert result.task.workstreams["main"].branch == "feat/issue-32-herdr-task-start"


def test_different_registered_worktree_is_rejected_without_herdr_mutation(
    start_fixture: StartFixture,
) -> None:
    start_fixture.run(32)
    before_state = start_fixture.state_bytes()
    before_calls = list(start_fixture.herdr.calls)
    start_fixture.use_second_valid_worktree("feat/issue-32-replacement")

    with pytest.raises(LifecycleError, match="different worktree"):
        start_fixture.run(32)

    assert start_fixture.state_bytes() == before_state
    assert start_fixture.herdr.calls == before_calls
```

Add branch-conflict and invalid-primary/detached/missing-marker cases. Every invalid case asserts unchanged state bytes and unchanged `FakeHerdr.calls`.

- [ ] **Step 2: Run startup tests to verify RED**

Run:

```bash
uv run --project tools/herdr_task_lifecycle --group dev pytest tools/herdr_task_lifecycle/tests/commands/start/test_service.py -v
```

Expected: the new tests fail because `TaskStarter` does not validate or store the Git worktree and branch, and its label has no `#` prefix.

- [ ] **Step 3: Integrate validation before Herdr reconciliation**

After the existing cwd shape checks and before `resolve_repository`, add:

```python
registration = resolve_managed_worktree(cwd, self._runner)
cwd = registration.path
```

Set `tab_label = f"#{issue_number} {short_title(title)}"`. Before `_workspace_for_repository`, compare existing `main.worktree` and `main.branch`, when present, with `registration.path` and `registration.branch`; mismatch raises `LifecycleError` without touching Herdr. Include these exact fields in the existing `updated_main = main.model_copy(update=...)` call:

```python
"worktree": str(registration.path),
"branch": registration.branch,
```

Do not change the existing resource rollback logic.

- [ ] **Step 4: Run startup tests to verify GREEN**

Run the Step 2 command again.

Expected: all start-service tests pass, including legacy upgrade, re-run reuse, conflict rejection, pre-Herdr validation, label formatting, and unrelated metadata preservation.

- [ ] **Step 5: Commit the integration**

```bash
git add tools/herdr_task_lifecycle/src/herdr_task_lifecycle/commands/start/service.py tools/herdr_task_lifecycle/tests/commands/start/test_service.py
git commit -m "feat: register worktrees during task startup" -m "Persist validated main-workstream paths and branches with Herdr resources." -m "Generated-by: Codex"
```

### Task 3: Document the operational contract and verify the branch

**Files:**

- Modify: `docs/HERDR-TASK-LIFECYCLE.md:16-95`
- Modify: `docs/HERDR-TASK-STATE.md:50-70`
- Modify: `README.md:104-116`
- Modify: `AGENTS.md:28-50`
- Modify: `tests/herdr_task_lifecycle_test.sh:1-16`

**Interfaces:**

- Consumes: Task 2's `herdr-task start ISSUE --cwd WORKTREE` contract.
- Produces: one documented start order: create a feature worktree in a marked task root, then call `start` from that worktree.
- Preserves: cleanup's plan, human approval, exact-root confirmation, and retry requirements.

- [ ] **Step 1: Add a failing documentation-contract check**

Extend the existing shell documentation test with these checks:

```bash
rg -q 'non-primary Git worktree' docs/HERDR-TASK-LIFECYCLE.md
rg -q 'worktree.*branch' docs/HERDR-TASK-LIFECYCLE.md
rg -q '#<issue-number> <short-title>' docs/HERDR-TASK-LIFECYCLE.md
rg -q 'create.*worktree.*then.*herdr-task start' AGENTS.md
```

The production behavior is protected by Tasks 1 and 2; this follows the repository's existing convention for protecting the operator-facing documentation contract.

- [ ] **Step 2: Run the documentation test to verify RED**

Run:

```bash
bash tests/herdr_task_lifecycle_test.sh
```

Expected: it fails because the current lifecycle text permits repository cwd use and documents the old unprefixed label.

- [ ] **Step 3: Update documentation**

Document that `--cwd` is a branch-attached registered non-primary Git worktree below a direct marker under `/home/takashi/work/tasks/`. State that `start` records and revalidates its resolved path and branch and rejects replacement paths/branches. Change all primary Tab examples to `#<issue-number> <short-title>`. Add the required create-worktree-then-start order to `AGENTS.md`; retain existing cleanup constraints. README and the state reference link to the canonical lifecycle details instead of duplicating its validation algorithm.

- [ ] **Step 4: Run full verification**

Run:

```bash
bash tests/herdr_task_lifecycle_test.sh
uv run --project tools/herdr_task_state --group dev pytest tools/herdr_task_state/tests
uv run --project tools/herdr_task_state --group dev ruff format --check tools/herdr_task_state/src tools/herdr_task_state/tests
uv run --project tools/herdr_task_state --group dev ruff check tools/herdr_task_state/src tools/herdr_task_state/tests
uv run --project tools/herdr_task_lifecycle --group dev pytest tools/herdr_task_lifecycle/tests
uv run --project tools/herdr_task_lifecycle --group dev ruff format --check tools/herdr_task_lifecycle/src tools/herdr_task_lifecycle/tests
uv run --project tools/herdr_task_lifecycle --group dev ruff check tools/herdr_task_lifecycle/src tools/herdr_task_lifecycle/tests
./tests/install_test.sh
```

Expected: every command exits 0 without formatting or lint errors.

- [ ] **Step 5: Commit and publish**

```bash
git add AGENTS.md README.md docs/HERDR-TASK-LIFECYCLE.md docs/HERDR-TASK-STATE.md tests/herdr_task_lifecycle_test.sh
git commit -m "docs: require worktrees for Herdr task startup" -m "Document validated worktree registration and Issue Tab labels." -m "Generated-by: Codex"
git push
```

Then inspect the branch before opening its Pull Request:

```bash
git diff --check origin/main...HEAD
git log --format='%B%n---' origin/main..HEAD
git status --short --branch
```

Create a Pull Request to `main`, request review from `dodo5522`, and do not merge it.
