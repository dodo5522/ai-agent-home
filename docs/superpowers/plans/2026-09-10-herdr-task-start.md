# Herdr Task Start Reconciliation Implementation Plan

> Implementation note: the initial plan below placed the start command in the
> state project. During implementation it was split into the independent
> `tools/herdr_task_start` project, which depends on the local
> `tools/herdr_task_state` package. The final source, tests, and uvx commands
> use that split layout.

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Add a herdr-task-start command that resolves a GitHub Issue, creates or reuses managed Herdr workspace/tab resources idempotently, and records runtime references in task state.

**Architecture:** Keep `herdr_task_state` independent of external commands. In the separate `herdr_task_start` package, `start.py` owns reconciliation, `herdr.py` owns the typed Herdr adapter, `identity.py` resolves Git/GitHub identity, and `runner.py` owns subprocess execution. `cli.py` remains a thin command entry point. Persist state only after all resource checks succeed and use state-stored IDs as ownership proof.

**Tech Stack:** Python 3.14.7 from mise, Pydantic 2.12.5, Python standard library (argparse, dataclasses, json, pathlib, re, subprocess), pytest 8.4.2, Ruff 0.14.10, Herdr CLI 0.8.2, GitHub CLI gh.

**Spec:** docs/superpowers/specs/2026-09-10-herdr-task-start-design.md

## Global Constraints

- Complex logic uses mise-managed Python; Bash is only a thin launcher.
- The command is runnable with uvx --from ./tools/herdr_task_start herdr-task-start.
- Keep the existing exact Pydantic/pytest/Ruff pins and use no new runtime dependency.
- Require HERDR_ENV=1 and use current cwd unless --cwd is supplied.
- Normalize GitHub identity to lower-case owner/name and use owner/name#issue-number as the stable key.
- Workspace label is owner/name. Tab label is issue-number plus normalized, 60-character short title.
- Only IDs already recorded in state may be reused; matching labels never import unmanaged resources.
- Creation commands pass --no-focus and the requested cwd.
- The selected tab must contain exactly one root pane; never mutate unmanaged resources.
- Write state only after successful reconciliation through StateStore.put.
- stdout emits one task JSON document on success; diagnostics go to stderr.
- Tests use temporary state and fake git, gh, and herdr executables.
- Every commit ends with the Generated-by: Codex trailer.

---

### Task 1: Resolve repository, Issue title, and labels

**Files:**
- Create: tools/herdr_task_state/src/herdr_task_state/start.py
- Create: tools/herdr_task_state/tests/test_herdr_task_start.py

**Interfaces:**
- CommandResult(returncode: int, stdout: str, stderr: str)
- CommandRunner.run(arguments: Sequence[str], cwd: Path | None = None) -> CommandResult
- TaskStartError(RuntimeError)
- resolve_repository(cwd: Path, runner: CommandRunner) -> str
- load_issue_title(repository: str, issue_number: int, runner: CommandRunner) -> str
- short_title(title: str) -> str

- [ ] Step 1: Write the failing tests.

Use real temporary fake executables and a fixture that records argument vectors. Add these tests:

~~~python
def test_resolve_repository_accepts_https_and_ssh_remotes(fake_runner):
    fake_runner.write_git_remote("git@github.com:Dodo5522/Ai-Agent-Home.git")
    assert resolve_repository(Path("/tmp/repo"), fake_runner) == "dodo5522/ai-agent-home"


def test_load_issue_title_uses_repository_and_json(fake_runner):
    fake_runner.write_gh_output({"title": "  Herdr   task-start  "})
    assert load_issue_title("dodo5522/ai-agent-home", 32, fake_runner) == "  Herdr   task-start  "


def test_short_title_normalizes_and_limits():
    assert short_title("  Herdr\nSpace   reconciliation ") == "Herdr Space reconciliation"
    assert len(short_title("x" * 61)) == 60
    assert short_title("x" * 61).endswith("…")


def test_rejects_non_github_remote(fake_runner):
    fake_runner.write_git_remote("https://example.invalid/repo.git")
    with pytest.raises(TaskStartError, match="GitHub remote"):
        resolve_repository(Path("/tmp/repo"), fake_runner)
~~~

Also test non-zero git/gh status and malformed title JSON. The expected failure is a missing start module, not a fixture error.

- [ ] Step 2: Run the focused test and verify RED.

~~~bash
uv run --project tools/herdr_task_state --group dev pytest -q tools/herdr_task_state/tests/test_herdr_task_start.py
~~~

Expected: collection fails because the new interfaces do not exist.

- [ ] Step 3: Implement the typed subprocess boundary.

Use subprocess.run with shell disabled and capture_output=True. Resolve the remote with git -C cwd remote get-url origin. Accept only GitHub HTTPS and SSH forms with an optional .git suffix; normalize owner/name to lower case. Invoke gh issue view issue-number --repo owner/name --json title and parse one object containing a non-empty string title. short_title collapses whitespace, strips it, and returns at most 60 characters, reserving the final character for … when truncated. Error messages contain only the operation and status, never arbitrary command output.

- [ ] Step 4: Run the focused test again and verify GREEN.

~~~bash
uv run --project tools/herdr_task_state --group dev pytest -q tools/herdr_task_state/tests/test_herdr_task_start.py
~~~

- [ ] Step 5: Commit.

~~~bash
git add tools/herdr_task_state/src/herdr_task_state/start.py tools/herdr_task_state/tests/test_herdr_task_start.py
git commit -m "feat: resolve task-start repository identity" -m "Add typed GitHub remote, Issue title, and deterministic label resolution for Herdr task startup.

Generated-by: Codex"
~~~

### Task 2: Add the typed Herdr CLI adapter

**Files:**
- Modify: tools/herdr_task_state/src/herdr_task_state/start.py
- Modify: tools/herdr_task_state/tests/test_herdr_task_start.py

**Interfaces:**
- WorkspaceInfo(workspace_id: str, label: str)
- TabInfo(tab_id: str, workspace_id: str, label: str)
- PaneInfo(pane_id: str, tab_id: str)
- CreatedResources(workspace_id: str, tab_id: str, pane_id: str)
- HerdrClient.workspace_get, workspace_create, workspace_close, tab_get, tab_create, tab_rename, tab_close, panes_for_workspace

- [ ] Step 1: Write failing fake-Herdr tests.

The fake executable returns the documented result objects and records arguments. Test workspace creation parsing and exact flags:

~~~python
def test_workspace_create_parses_ids_and_no_focus(fake_herdr):
    fake_herdr.respond("workspace create", {
        "result": {
            "workspace": {"workspace_id": "w9", "label": "dodo5522/ai-agent-home"},
            "tab": {"tab_id": "w9:t2", "workspace_id": "w9", "label": "1"},
            "root_pane": {"pane_id": "w9:p3", "tab_id": "w9:t2"},
        }
    })
    created = fake_herdr.client.workspace_create(
        "dodo5522/ai-agent-home", Path("/tmp/work")
    )
    assert created == CreatedResources("w9", "w9:t2", "w9:p3")
    assert fake_herdr.last_call == [
        "workspace", "create", "--label", "dodo5522/ai-agent-home",
        "--cwd", "/tmp/work", "--no-focus",
    ]
~~~

Add tests for tab create/rename, get identity parsing, pane filtering by tab ID, non-zero status, malformed JSON, and missing IDs.

- [ ] Step 2: Run the adapter test and verify RED.

~~~bash
uv run --project tools/herdr_task_state --group dev pytest -q tools/herdr_task_state/tests/test_herdr_task_start.py -k herdr
~~~

- [ ] Step 3: Implement HerdrClient.

Execute commands as argument arrays beginning with herdr. Use these exact command forms:

~~~text
herdr workspace get WORKSPACE_ID
herdr workspace create --label LABEL --cwd CWD --no-focus
herdr tab get TAB_ID
herdr tab create --workspace WORKSPACE_ID --cwd CWD --label LABEL --no-focus
herdr tab rename TAB_ID LABEL
herdr tab close TAB_ID
herdr workspace close WORKSPACE_ID
herdr pane list --workspace WORKSPACE_ID
~~~

Parse one JSON object and require every expected ID and membership field. panes_for_workspace filters pane objects by tab_id. Never rely on list ordering or predicted IDs.

- [ ] Step 4: Run the adapter test and verify GREEN.

~~~bash
uv run --project tools/herdr_task_state --group dev pytest -q tools/herdr_task_start/tests/test_herdr_task_start.py -k herdr
~~~

- [ ] Step 5: Commit.

~~~bash
git add tools/herdr_task_state/src/herdr_task_state/start.py tools/herdr_task_state/tests/test_herdr_task_start.py
git commit -m "feat: add typed Herdr task-start client" -m "Parse workspace, tab, and pane JSON responses without relying on display order or fixed IDs.

Generated-by: Codex"
~~~

### Task 3: Reconcile resources and persist state

**Files:**
- Modify: tools/herdr_task_state/src/herdr_task_state/start.py
- Modify: tools/herdr_task_state/tests/test_herdr_task_start.py

**Interfaces:**
- TaskStartResolution(task: Task, task_key: TaskKey, workspace_id: str, tab_id: str, pane_id: str, cwd: Path)
- TaskStarter.start(issue_number: int, cwd: Path) -> TaskStartResolution

- [ ] Step 1: Write failing reconciliation tests.

Use fixtures for state, fake GitHub, and fake Herdr. Cover first creation, sequential reuse, stale IDs, unmanaged same-label resources, multiple panes, failed create/rename/state write, and metadata preservation. The core assertions are:

~~~python
def test_first_start_creates_and_persists(start_fixture):
    result = start_fixture.run(32)
    assert result.workspace_id == "w9"
    assert result.tab_id == "w9:t2"
    assert result.pane_id == "w9:p3"
    assert result.task.workstreams["main"].pane_ids == {"root": "w9:p3"}


def test_second_start_reuses_without_duplicate_create(start_fixture):
    first = start_fixture.run(32)
    second = start_fixture.run(32)
    assert second.task == first.task
    assert start_fixture.count_calls("workspace", "create") == 1


def test_stale_state_does_not_import_label_only_resource(start_fixture):
    start_fixture.write_state_with_ids("w-stale", "w-stale:t1", "w-stale:p1")
    result = start_fixture.run(32)
    assert result.workspace_id == "w-new"
    assert not start_fixture.was_called("workspace", "rename")


def test_multiple_panes_fail_without_state_update(start_fixture):
    before = start_fixture.state_bytes()
    start_fixture.herdr_tab_panes("w9:t2", ["w9:p1", "w9:p2"])
    with pytest.raises(TaskStartError, match="exactly one pane"):
        start_fixture.run(32)
    assert start_fixture.state_bytes() == before
~~~

- [ ] Step 2: Run reconciliation tests and verify RED.

~~~bash
uv run --project tools/herdr_task_state --group dev pytest -q tools/herdr_task_state/tests/test_herdr_task_start.py -k reconciliation
~~~

Expected: failures because TaskStarter and TaskStartResolution do not exist.

- [ ] Step 3: Implement TaskStarter.

Before any mutation reject missing HERDR_ENV, invalid issue numbers, and invalid cwd. Read an existing state file with StateStore; when absent, use an in-memory empty TaskState without creating a file. Gather distinct workspace IDs from tasks with the same repository, validate each with workspace_get, and reuse exactly one live candidate with the exact label. If none is valid, call workspace_create and rename only its returned root tab.

For the target task, validate a stored tab with tab_get (workspace membership and exact label) and panes_for_workspace (exactly one pane). If stale, mismatched, absent, or multi-pane, create a new tab with the requested cwd, label, and --no-focus; do not mutate the old tab. For a newly created tab, validate the returned root pane and exactly-one-pane invariant.

Create or update Task while preserving unrelated fields/workstreams. Set title, HerdrReference(workspace_id, workspace_label), main.tab_id, main.tab_label, and main.pane_ids.root. Call StateStore.put once after all checks. Track only resources created by this invocation for best-effort rollback after later failures; never close state-owned or unmanaged resources.

- [ ] Step 4: Run reconciliation tests and verify GREEN.

~~~bash
uv run --project tools/herdr_task_state --group dev pytest -q tools/herdr_task_state/tests/test_herdr_task_start.py -k reconciliation
~~~

- [ ] Step 5: Commit.

~~~bash
git add tools/herdr_task_state/src/herdr_task_state/start.py tools/herdr_task_state/tests/test_herdr_task_start.py
git commit -m "feat: reconcile managed Herdr task resources" -m "Create or reuse repository workspaces and Issue tabs, validate root panes, and persist runtime references only after success.

Generated-by: Codex"
~~~

### Task 4: Expose the uvx CLI

**Files:**
- Modify: tools/herdr_task_state/pyproject.toml
- Create: tools/herdr_task_state/src/herdr_task_state/start_cli.py
- Create: bin/herdr-task-start
- Modify: tools/herdr_task_state/tests/test_herdr_task_start.py

**Interfaces:**
- start_cli.main(argv: Sequence[str] | None = None) -> int
- Command: herdr-task-start ISSUE_NUMBER [--cwd PATH]

- [ ] Step 1: Write failing CLI tests.

Invoke bin/herdr-task-start with fake executable paths and assert help documents ISSUE_NUMBER/--cwd, successful output is one task JSON document, invalid issue returns ExitCode.USAGE_ERROR, and missing HERDR_ENV returns ExitCode.RUNTIME_ERROR. Also assert uvx --from ./tools/herdr_task_state herdr-task-start --help exits zero.

- [ ] Step 2: Run the CLI tests and verify RED.

~~~bash
uv run --project tools/herdr_task_state --group dev pytest -q tools/herdr_task_state/tests/test_herdr_task_start.py -k cli
~~~

Expected: failure because the console script, CLI module, and launcher do not exist.

- [ ] Step 3: Implement the console script and launcher.

Add this script entry to pyproject.toml:

~~~toml
[project.scripts]
herdr-task-state = "herdr_task_state.cli:main"
herdr-task-start = "herdr_task_state.start_cli:main"
~~~

Use existing ExitCode meanings and argparse descriptions. Resolve --cwd to an absolute directory, call TaskStarter.start, print Task.to_json(), and send diagnostics to stderr. The launcher is:

~~~bash
#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
UV_BIN=/home/takashi/.local/share/mise/shims/uv
exec "$UV_BIN" run --project "$SCRIPT_DIR/../tools/herdr_task_state" herdr-task-start "$@"
~~~

- [ ] Step 4: Run the CLI tests and verify GREEN.

~~~bash
uv run --project tools/herdr_task_state --group dev pytest -q tools/herdr_task_state/tests/test_herdr_task_start.py -k cli
uvx --from ./tools/herdr_task_state herdr-task-start --help
~~~

Expected: all focused tests pass and help exits 0 without creating resources.

- [ ] Step 5: Commit.

~~~bash
git add tools/herdr_task_state/pyproject.toml tools/herdr_task_state/src/herdr_task_state/start_cli.py bin/herdr-task-start tools/herdr_task_state/tests/test_herdr_task_start.py tools/herdr_task_state/uv.lock
git commit -m "feat: expose Herdr task-start command" -m "Package the reconciler as a uvx-runnable CLI with explicit Issue and cwd arguments.

Generated-by: Codex"
~~~

### Task 5: Document and verify installation contract

**Files:**
- Modify: README.md
- Modify: docs/HERDR-TASK-STATE.md
- Modify: tests/install_test.sh

**Interfaces:**
- Documentation describes task-start without duplicating lifecycle tables owned by Issue #33.
- Installer checks verify the launcher, project metadata, and uvx help path.

- [ ] Step 1: Add failing installer assertions.

Add paths for bin/herdr-task-start and the project metadata. Assert executable existence, the herdr-task-start project script, uvx help, HERDR_ENV=1, --no-focus, owner/name#issue-number, and the managed/unmanaged ownership rule. Add README/operator-reference assertions for command usage and the no-read-only-resource guarantee.

- [ ] Step 2: Run the installer test and verify RED.

~~~bash
bash tests/install_test.sh
~~~

Expected: the new assertions fail before documentation and launcher checks are added.

- [ ] Step 3: Update documentation.

Add the example:

~~~bash
uvx --from ./tools/herdr_task_state herdr-task-start 32
~~~

Document Git remote/Issue title resolution, --cwd, deterministic labels, state-owned IDs, stale replacement, one-root-pane validation, --no-focus, failure behavior, and that read-only state commands never create resources. Link lifecycle cleanup details to Issue #33.

- [ ] Step 4: Run installer checks and verify GREEN.

~~~bash
bash tests/install_test.sh
~~~

- [ ] Step 5: Commit.

~~~bash
git add README.md docs/HERDR-TASK-STATE.md tests/install_test.sh
git commit -m "docs: document Herdr task-start operations" -m "Describe task-start invocation, ownership checks, and safe Space/Tab reconciliation for operators and installers.

Generated-by: Codex"
~~~

### Task 6: Full verification and handoff

**Files:**
- Test: tools/herdr_task_state/tests/test_herdr_task_state.py
- Test: tools/herdr_task_state/tests/test_herdr_task_state_cli.py
- Test: tools/herdr_task_start/tests/test_herdr_task_start.py
- Test: tests/herdr_task_state_test.sh
- Test: tests/herdr_task_start_test.sh
- Test: tests/install_test.sh

- [ ] Step 1: Run the full Python suite.

~~~bash
uv run --project tools/herdr_task_state --group dev pytest -q tools/herdr_task_state/tests
uv run --project tools/herdr_task_start --group dev pytest -q tools/herdr_task_start/tests
~~~

Expected: all existing and new tests pass.

- [ ] Step 2: Run formatting and lint checks.

~~~bash
uv run --project tools/herdr_task_state --group dev ruff format --check tools/herdr_task_state/src tools/herdr_task_state/tests
uv run --project tools/herdr_task_state --group dev ruff check tools/herdr_task_state/src tools/herdr_task_state/tests
uv run --project tools/herdr_task_start --group dev ruff format --check tools/herdr_task_start/src tools/herdr_task_start/tests
uv run --project tools/herdr_task_start --group dev ruff check tools/herdr_task_start/src tools/herdr_task_start/tests
~~~

- [ ] Step 3: Run shell and diff checks.

~~~bash
bash tests/herdr_task_state_test.sh
bash tests/herdr_task_start_test.sh
bash tests/install_test.sh
git diff --check
~~~

Expected: all checks exit 0, stdout remains machine-readable for CLI tests, and git diff --check reports no whitespace errors.

- [ ] Step 4: Inspect scope and trailers.

~~~bash
git status --short --branch
git diff origin/main...HEAD --stat
git log origin/main..HEAD --format='%H%n%B%n---'
~~~

Confirm no state files, credentials, private keys, virtualenvs, or generated build artifacts are tracked; only Issue #32 files changed; every commit has Generated-by: Codex.

- [ ] Step 5: Push and open/update the PR.

~~~bash
git push -u origin feat/issue-32-herdr-task-start-impl
~~~

Use an ephemeral GitHub App Installation token through GH_TOKEN to create/update a PR targeting main and request dodo5522. Do not merge the PR.
