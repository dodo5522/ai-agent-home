# Herdr Task State Python Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reimplement the approved Herdr task-state contract with mise-managed Python for non-trivial logic, leaving Bash only as a thin launcher.

**Architecture:** `bin/herdr-task-state` delegates to the uv-managed package without implementing state logic. `tools/herdr_task_state/src/herdr_task_state/model.py` owns Pydantic models, JSON parsing, and schema validation; `store.py` owns locking, permissions, and atomic replacement; `cli.py` owns command dispatch and exit-code mapping. Pytest tests exercise the tool through shared fixtures, and Ruff formats/lints the Python sources.

**Tech Stack:** Python `3.14.7` from `.config/mise/config.toml`, Pydantic for model validation, Python standard library (`argparse`, `fcntl`, `json`, `os`, `pathlib`, `re`, `stat`, `tempfile`), Bash wrapper, mise `uv = "0.12.11"`, package execution through `uvx`, pytest fixtures, and pinned Ruff formatting/linting.

**Spec:** `docs/superpowers/specs/2026-09-08-herdr-task-state-design.md`

## Policy decisions

- Complex state and validation logic must be Python executed through the mise-managed Python version.
- Bash is limited to simple orchestration and launching the Python tool.
- Prefer Python standard-library modules.
- No third-party package is needed for this state tool; therefore do not add a Python dependency or lockfile solely for it.
- `uv` is still pinned in mise at the current version `0.12.11` for future Python tooling and packaging.
- The tool is packaged independently in `tools/herdr_task_state/pyproject.toml` and must be runnable as `uvx --from ./tools/herdr_task_state herdr-task-state ...`.
- Tests use pytest fixtures; Ruff is the repository formatter and linter.
- Pydantic is the only runtime third-party dependency; its exact version is locked per tool.
- If a future third-party dependency materially reduces code, add it with `uv` and commit its lockfile with an exact version.

## Global constraints

- Preserve the design's JSON schema, stable Issue/workstream keys, CLI commands, exit statuses, state path, permissions, lock, atomic update, and no-secrets contract.
- The default state path is `${XDG_STATE_HOME:-$HOME/.local/state}/ai-agent-home/herdr-tasks.json`; `HERDR_TASK_STATE_FILE` overrides it only with an absolute path.
- State directory mode is `0700`; state and adjacent lock file modes are `0600`.
- Lock before every mutating read-modify-write; write a same-directory temporary and atomically replace the destination.
- Never replace invalid or dangling existing state with an empty document.
- stdout is JSON only for `validate`, `get`, `put`, and `remove`; `init` succeeds silently; diagnostics go to stderr.
- Exit statuses are `0` success, `1` filesystem/runtime, `2` usage/validation, and `3` missing `get` task.
- Tests use a temporary override and never touch the real user state.
- Every intended Git commit has the `Generated-by: Codex` trailer.

---

### Task 1: Python domain and schema module

**Files:**
- Delete: `lib/herdr-task-state.jq`
- Create: `tools/herdr_task_state/src/herdr_task_state/__init__.py`
- Create: `tools/herdr_task_state/src/herdr_task_state/model.py`
- Create: `tools/herdr_task_state/tests/test_herdr_task_state.py`
- Modify: `tests/herdr_task_state_test.sh`

**Interfaces:**
- `model.py`: `TaskKey.parse(value) -> TaskKey`.
- `model.py`: Pydantic models, strict JSON parsing, cross-field validation, and safe validation errors.
- Test wrapper: `tests/herdr_task_state_test.sh` invokes the tool-local uv project and pytest only.

- [ ] Add failing pytest cases for valid empty/example state, malformed keys, missing main, identity mismatch, invalid paths/slugs/PR arrays, unsupported version, and unknown-field preservation.
- [ ] Run the focused Python test and confirm it fails because the module does not exist.
- [ ] Implement Pydantic models with field-level constraints and model-level cross-field validation.
- [ ] Ensure repository/key normalization follows the design regex and Issue numbers are positive decimal integers without leading zeroes.
- [ ] Ensure validation accepts unknown fields while enforcing required fields and cross-field identity.
- [ ] Replace the shell test body with a thin wrapper using the mise-managed uv shim and tool-local pytest.
- [ ] Run the tool-local pytest, Ruff, shell syntax, and existing installer tests.
- [ ] Commit: `feat: move Herdr task validation to Python` with the required trailer.

---

### Task 2: Python state store and CLI

**Files:**
- Create: `tools/herdr_task_state/src/herdr_task_state/store.py`
- Create: `tools/herdr_task_state/src/herdr_task_state/cli.py`
- Create: `tools/herdr_task_state/src/herdr_task_state/__main__.py`
- Replace: `bin/herdr-task-state`
- Modify: `tools/herdr_task_state/tests/test_herdr_task_state.py`

**Interfaces:**
- `store.py`: `StateStore(path: Path)`, `init()`, `read()`, `get(task_key)`, `put(task_key, task_document)`, `remove(task_key)`.
- `cli.py`: `main(argv: Sequence[str]) -> int`, mapping typed exceptions to exit statuses.
- `bin/herdr-task-state`: shell-only launcher that executes the mise Python entry point.

- [ ] Add failing tests for CLI `init`, `validate`, `get`, `put`, and `remove`, including stdout/stderr and exit status assertions.
- [ ] Add failing tests for default/override path resolution, directory/file/lock modes, invalid existing state, dangling symlink, and absent task.
- [ ] Run focused tests and capture the expected failures.
- [ ] Implement typed `StateStore` methods over `TaskState` and `Task` with `fcntl.flock` on `<state>.lock`, `os.umask(0o077)`, path checks, same-directory temporary writes, `os.chmod`, `os.replace`, and exact temporary cleanup.
- [ ] Snapshot and validate one input task document before acquiring the state lock; reuse that immutable object for candidate state and stdout.
- [ ] Keep `init` silent on success; emit JSON for `validate`, `get`, `put`, and `remove`.
- [ ] Implement `argparse` only in Python; keep the shell wrapper free of command parsing.
- [ ] Run focused Python tests, wrapper syntax, installer tests, and `git diff --check`.
- [ ] Commit: `feat: implement Python Herdr task state CLI` with the required trailer.

---

### Task 3: Concurrency, failure, and regression coverage

**Files:**
- Modify: `tools/herdr_task_state/tests/test_herdr_task_state.py`
- Modify: `tests/herdr_task_state_test.sh`
- Modify: `tests/install_test.sh`

- [ ] Add tests for 20 concurrent `put` processes preserving every task and each process's JSON output.
- [ ] Add tests under permissive umask for `0700` state directory and `0600` state/lock files.
- [ ] Add filesystem failure tests asserting exit `1`, nonempty stderr, empty stdout, and no partial destination.
- [ ] Add regular-file source replacement regression proving `put` stores/emits the validated snapshot rather than rereading a changed file.
- [ ] Add installer assertions for Python entry point, wrapper, no jq-module runtime dependency, and exact silent-init/exit-code/no-secrets documentation wording.
- [ ] Run Python tests, shell wrapper, installer tests, `bash -n`, `git diff --check`, and conditional ShellCheck.
- [ ] Commit: `test: harden Python Herdr task state` with the required trailer.

---

### Task 4: mise/uv and documentation alignment

**Files:**
- Modify: `.config/mise/config.toml`
- Create: `tools/herdr_task_state/pyproject.toml`
- Create: `tools/herdr_task_state/uv.lock`
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `docs/HERDR-TASK-STATE.md`
- Modify: `tests/install_test.sh`

- [ ] Add `uv = "0.12.11"` to the mise tool list and update documentation's tool verification examples.
- [ ] Record the Python/Bash implementation boundary, mise-managed Python requirement, stdlib preference, and uv version/dependency policy in `AGENTS.md`.
- [ ] Keep the tool's exact pytest/Ruff dependency versions in `tools/herdr_task_state/uv.lock`.
- [ ] Document that complex state logic is Python, the wrapper is Bash-only, Python is supplied by mise, and uv is pinned for future tooling.
- [ ] Document the Python CLI contract, state schema, permissions, lock, atomicity, and no-secrets rules without duplicating the future Space/Tab lifecycle table owned by #33.
- [ ] Run `mise install`/tool verification in dry-run-compatible tests where possible, Python tests, installer tests, shell syntax, and diff checks.
- [ ] Commit: `build: pin uv in mise configuration` with the required trailer.

---

### Task 5: Delivery

- [ ] Run all tests with the mise Python, inspect scope and secrets, verify every commit trailer, and confirm the branch is clean.
- [ ] Push `feat/issue-31-herdr-task-state` and update the existing PR #34; do not create a second PR.
- [ ] Request/retain review from `dodo5522` and report the updated PR state.
