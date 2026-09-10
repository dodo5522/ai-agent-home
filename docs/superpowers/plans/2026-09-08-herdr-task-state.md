# Herdr Task State Foundation Implementation Plan

> **Superseded:** The implementation policy changed on 2026-09-09. Use [`2026-09-09-herdr-task-state-python.md`](2026-09-09-herdr-task-state-python.md) for execution; this file records the earlier shell/jq plan for historical context.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a private, versioned JSON state store that maps stable GitHub Issue task identities to Herdr, worktree, Agent, PR, and Codex session references without lost or partial updates.

**Architecture:** `bin/herdr-task-state` owns CLI parsing, filesystem permissions, locking, and atomic replacement. `lib/herdr-task-state.jq` owns schema and cross-field validation so every read and write uses one validation contract. A shell test suite uses only temporary state paths and drives the executable as a black box.

**Tech Stack:** Bash 5, jq, flock from util-linux, GNU coreutils, Git

**Spec:** `docs/superpowers/specs/2026-09-08-herdr-task-state-design.md`

## Global Constraints

- The default state path is `${XDG_STATE_HOME:-$HOME/.local/state}/ai-agent-home/herdr-tasks.json`.
- `HERDR_TASK_STATE_FILE` may override the path, but the resolved path must be absolute.
- State directory mode is `0700`; state and adjacent lock file modes are `0600`.
- The adjacent `<state-file>.lock` file is locked before every mutating read-modify-write.
- A successful update writes a same-directory temporary file and atomically renames it over the state file.
- Invalid input or existing state never causes replacement with an empty document.
- The only supported top-level schema version is integer `1`.
- Issue task keys have the form `<lower-case-owner>/<lower-case-repository>#<positive-issue-number>`.
- Every task has a `main` workstream; PR numbers are metadata, never identity.
- Unknown fields are allowed inside recognized objects; changing a defined field's meaning or type requires a schema version change.
- The state file stores no token, credential, private key, or authentication material and is not committed to Git.
- stdout contains machine-readable JSON only; diagnostics go to stderr.
- Exit statuses are `0` success, `1` runtime/filesystem failure, `2` usage or validation failure, and `3` missing task from `get`.
- Tests must never read or modify the real user state file.

---

### Task 1: Schema validator

**Files:**
- Create: `lib/herdr-task-state.jq`
- Create: `tests/herdr_task_state_test.sh`

**Interfaces:**
- Consumes: a JSON document on jq input.
- Produces: jq functions `valid_task_key($key)`, `valid_workstream`, `valid_task($key)`, and `valid_state`; each returns a boolean and emits no transformed data.

- [ ] **Step 1: Add a failing black-box validator fixture test**

Create `tests/herdr_task_state_test.sh` with a private temporary directory, cleanup trap, assertion helpers, and direct jq calls while the CLI does not yet exist:

```bash
#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
JQ_LIB_DIR="$REPO_ROOT/lib"
TEST_ROOT=$(mktemp -d)
trap 'rm -rf "$TEST_ROOT"' EXIT
failures=0

fail() { printf 'not ok - %s\n' "$1"; failures=$((failures + 1)); }
pass() { printf 'ok - %s\n' "$1"; }

assert_valid() {
    local description=$1 file=$2
    if jq -L "$JQ_LIB_DIR" -e 'include "herdr-task-state"; valid_state' "$file" >/dev/null; then
        pass "$description"
    else
        fail "$description"
    fi
}

assert_invalid() {
    local description=$1 file=$2
    if jq -L "$JQ_LIB_DIR" -e 'include "herdr-task-state"; valid_state' "$file" >/dev/null 2>&1; then
        fail "$description"
    else
        pass "$description"
    fi
}
```

Add literal fixtures for an empty version 1 document and the complete example from the design spec. Add invalid fixtures for version `2`, malformed task key, missing `main`, a relative `worktree`, duplicate PR numbers, zero PR number, invalid role slug, empty Agent name, and a repository/Issue mismatch with the map key. End the script by exiting nonzero when `failures > 0`.

- [ ] **Step 2: Run the validator test and verify it fails**

Run:

```bash
./tests/herdr_task_state_test.sh
```

Expected: FAIL because `lib/herdr-task-state.jq` cannot be loaded.

- [ ] **Step 3: Implement the jq validation module**

Create focused predicates in `lib/herdr-task-state.jq`. Use the following public structure and keep helper functions private by naming convention:

```jq
def _nonempty_string: type == "string" and length > 0;
def _repository: _nonempty_string and test("^[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*$");
def _slug: _nonempty_string and test("^[a-z][a-z0-9-]{0,31}$");
def _positive_integer: type == "number" and floor == . and . > 0;

def valid_task_key($key):
  ($key | type == "string") and
  (try ($key | capture("^(?<repository>[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*)#(?<issue>[1-9][0-9]*)$")) catch false) != false;

def valid_workstream:
  type == "object"
  and ((has("tab_id") | not) or (.tab_id | _nonempty_string))
  and ((has("tab_label") | not) or (.tab_label | _nonempty_string))
  and ((has("worktree") | not) or (.worktree | _nonempty_string and startswith("/")))
  and ((has("branch") | not) or (.branch | _nonempty_string))
  and ((.pull_requests // []) | type == "array" and all(.[]; _positive_integer) and (length == (unique | length)))
  and ((.pane_ids // {}) | type == "object" and all(to_entries[]; (.key | _slug) and (.value | _nonempty_string)))
  and ((.agents // {}) | type == "object" and all(to_entries[];
    (.key | _slug)
    and (.value | type == "object")
    and (.value.name | _nonempty_string)
    and ((.value | has("codex_session_id") | not) or (.value.codex_session_id | _nonempty_string)))) ;
```

Implement `valid_task($key)` by capturing repository and Issue from `$key`, comparing both to `.repository` and `.issue_number`, requiring `workstreams.main`, validating every workstream key with `_slug`, and applying `valid_workstream` to every value. Implement `valid_state` by requiring `{version: 1, tasks: object}` and validating every task entry. Unknown fields must not invalidate otherwise valid objects.

- [ ] **Step 4: Run the validator tests and jq syntax check**

Run:

```bash
jq -n -L lib 'include "herdr-task-state"; true'
./tests/herdr_task_state_test.sh
```

Expected: jq exits `0`; every validator case prints `ok` and the test exits `0`.

- [ ] **Step 5: Commit the schema validator**

```bash
git add lib/herdr-task-state.jq tests/herdr_task_state_test.sh
git commit -m "feat: validate Herdr task state schema" -m "Add version 1 task, workstream, and runtime-reference validation.\n\nGenerated-by: Codex"
```

---

### Task 2: Read-only state CLI

**Files:**
- Create: `bin/herdr-task-state`
- Modify: `tests/herdr_task_state_test.sh`

**Interfaces:**
- Consumes: `HERDR_TASK_STATE_FILE`, or the default XDG state path; commands `init`, `validate`, and `get <task-key>`.
- Produces: normalized JSON on stdout; exit `3` for an absent `get`; functions internal to the script named `resolve_paths`, `validate_key`, `validate_file`, and `with_exclusive_lock` for later mutation tasks.

- [ ] **Step 1: Add failing CLI tests for init, validate, and get**

Extend the test harness:

```bash
STATE_FILE="$TEST_ROOT/state/herdr-tasks.json"
CLI="$REPO_ROOT/bin/herdr-task-state"
export HERDR_TASK_STATE_FILE="$STATE_FILE"
```

Add tests that verify:

```bash
"$CLI" init
jq -e '. == {version: 1, tasks: {}}' "$STATE_FILE"
before=$(sha256sum "$STATE_FILE")
"$CLI" init
after=$(sha256sum "$STATE_FILE")
[[ $before == "$after" ]]
"$CLI" validate | jq -e '.version == 1'
```

Write a valid fixture containing `dodo5522/ai-agent-home#30`, then assert `get` emits exactly that task object. Capture the exit status for a missing key and assert it is `3`. Assert malformed keys, missing state, invalid state, an unsupported version, extra CLI arguments, and a relative `HERDR_TASK_STATE_FILE` fail with the specified exit class and do not put diagnostics on stdout.

- [ ] **Step 2: Run the CLI tests and verify they fail**

Run:

```bash
./tests/herdr_task_state_test.sh
```

Expected: FAIL because `bin/herdr-task-state` does not exist.

- [ ] **Step 3: Implement path resolution, validation, init, and get**

Create `bin/herdr-task-state` with `set -euo pipefail`, `umask 077`, and a repository-relative jq library path:

```bash
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
JQ_LIB_DIR=$(cd "$SCRIPT_DIR/../lib" && pwd)
STATE_FILE=${HERDR_TASK_STATE_FILE:-${XDG_STATE_HOME:-$HOME/.local/state}/ai-agent-home/herdr-tasks.json}
LOCK_FILE="${STATE_FILE}.lock"

case "$STATE_FILE" in
    /*) ;;
    *) printf 'herdr-task-state: state path must be absolute: %s\n' "$STATE_FILE" >&2; exit 2 ;;
esac
```

Implement:

```bash
validate_key() {
    jq -n -L "$JQ_LIB_DIR" -e --arg key "$1" \
        'include "herdr-task-state"; valid_task_key($key)' >/dev/null
}

validate_file() {
    jq -L "$JQ_LIB_DIR" -e \
        'include "herdr-task-state"; select(valid_state)' "$1"
}
```

`init` is a mutating command and must create the parent directory with `install -d -m 0700`, acquire descriptor 9 on the adjacent lock file, set it to `0600`, and use `flock -x 9`. If state exists, validate it without rewriting. Otherwise write the empty document through a same-directory `mktemp` file and `mv`.

`validate` requires an existing file and emits the validated document. `get` validates the key and document, uses `jq -e --arg key "$key" '.tasks[$key] // empty'`, and maps the empty result to exit `3`. Catch jq validation failure and translate it to exit `2`; reserve exit `1` for missing files, mkdir/open/lock failures, and other filesystem failures.

- [ ] **Step 4: Run CLI and regression tests**

Run:

```bash
bash -n bin/herdr-task-state
./tests/herdr_task_state_test.sh
./tests/install_test.sh
```

Expected: all commands exit `0`; all test assertions print `ok`.

- [ ] **Step 5: Commit the read-only CLI**

```bash
git add bin/herdr-task-state tests/herdr_task_state_test.sh
git commit -m "feat: add Herdr task state reader" -m "Initialize, validate, and query private versioned task state.\n\nGenerated-by: Codex"
```

---

### Task 3: Atomic put and remove

**Files:**
- Modify: `bin/herdr-task-state`
- Modify: `tests/herdr_task_state_test.sh`

**Interfaces:**
- Consumes: `put <task-key> <task-json-file>` and `remove <task-key>`.
- Produces: the stored task from `put`; the resulting complete state document from `remove`; preserves all unrelated task keys under one exclusive lock.

- [ ] **Step 1: Add failing mutation tests**

Add tests that create separate task JSON files and verify:

```bash
"$CLI" put 'dodo5522/ai-agent-home#30' "$TASK_30" | jq -e '.issue_number == 30'
"$CLI" put 'dodo5522/ai-agent-home#31' "$TASK_31" | jq -e '.issue_number == 31'
jq -e '.tasks | keys == ["dodo5522/ai-agent-home#30", "dodo5522/ai-agent-home#31"]' "$STATE_FILE"
"$CLI" remove 'dodo5522/ai-agent-home#30' | jq -e '.tasks | has("dodo5522/ai-agent-home#30") | not'
"$CLI" remove 'dodo5522/ai-agent-home#30'
```

Also assert that a mismatched task object, malformed input file, missing input file, unsupported current state, and invalid task key do not change the state checksum. Verify `put` does not accept stdin in place of a file and that extra arguments return exit `2`.

- [ ] **Step 2: Run mutation tests and verify they fail**

Run:

```bash
./tests/herdr_task_state_test.sh
```

Expected: FAIL because `put` and `remove` are unknown commands.

- [ ] **Step 3: Implement a shared atomic mutation helper**

Add a helper whose lock covers reading, mutation, validation, and rename:

```bash
write_candidate() {
    local candidate=$1 temp_file
    temp_file=$(mktemp "$(dirname "$STATE_FILE")/.herdr-tasks.XXXXXX") || return 1
    TEMP_FILE=$temp_file
    if ! validate_file "$candidate" >"$temp_file"; then
        rm -f -- "$temp_file"
        TEMP_FILE=""
        return 2
    fi
    chmod 0600 "$temp_file" || return 1
    mv -f -- "$temp_file" "$STATE_FILE" || return 1
    TEMP_FILE=""
}
```

Do not use an unresolved glob in cleanup. Install one trap that removes only non-empty `TEMP_FILE` after confirming its parent is the resolved state directory.

For `put`, validate the task file as an object using `valid_task($key)`, acquire the lock, validate or initialize the complete current document, and build the candidate with:

```bash
jq --arg key "$key" --slurpfile task "$task_file" \
    '.tasks[$key] = $task[0]' "$current_file"
```

For `remove`, acquire the same lock, validate current state, and build the candidate with `jq --arg key "$key" 'del(.tasks[$key])'`. An absent key succeeds and produces the unchanged logical document. Never delete external Herdr or Git resources in this CLI.

- [ ] **Step 4: Run mutation and regression tests**

Run:

```bash
bash -n bin/herdr-task-state
./tests/herdr_task_state_test.sh
./tests/install_test.sh
```

Expected: all commands exit `0`; invalid-update checks preserve the previous checksum.

- [ ] **Step 5: Commit atomic mutations**

```bash
git add bin/herdr-task-state tests/herdr_task_state_test.sh
git commit -m "feat: update Herdr task state atomically" -m "Serialize task updates with flock and same-directory atomic replacement.\n\nGenerated-by: Codex"
```

---

### Task 4: Concurrency, permissions, and failure hardening

**Files:**
- Modify: `bin/herdr-task-state`
- Modify: `tests/herdr_task_state_test.sh`

**Interfaces:**
- Consumes: the CLI from Tasks 2 and 3 under concurrent independent processes.
- Produces: deterministic private files, no lost successful `put`, no partial state, and precise stdout/stderr/exit behavior.

- [ ] **Step 1: Add failing concurrency and permission tests**

Use a fresh state path, initialize it, generate 20 valid task files, then run puts concurrently:

```bash
for issue in $(seq 101 120); do
    "$CLI" put "dodo5522/ai-agent-home#$issue" "$TEST_ROOT/task-$issue.json" >"$TEST_ROOT/out-$issue" &
done
wait
jq -e '.tasks | length == 20' "$STATE_FILE"
```

Assert every output file contains only the matching task JSON. Check modes using GNU `stat -c '%a'`: parent directory `700`, state `600`, and lock `600`. Start from a permissive process umask to prove the CLI still enforces private modes. Add a test where the destination directory is unwritable or replaced with a non-directory and assert exit `1`, a stderr diagnostic, empty stdout, and no partial destination file.

- [ ] **Step 2: Run the hardening tests and observe any failure**

Run:

```bash
./tests/herdr_task_state_test.sh
```

Expected before hardening: at least the permissive-mode or filesystem-failure assertion fails if Tasks 2–3 did not fully enforce the contract. If all new tests already pass, record that result and continue by auditing the implementation against Step 3 rather than weakening the assertions.

- [ ] **Step 3: Harden permissions, traps, and error translation**

Ensure the implementation:

- runs with `umask 077` before creating any file;
- applies `chmod 0700` to the managed state directory without changing unrelated ancestors;
- applies `chmod 0600` to the lock and replacement file;
- uses one exclusive lock across the complete read-modify-write window;
- checks every `mktemp`, `chmod`, validation, and `mv` result;
- removes only the exact same-directory temporary file owned by the current process;
- maps validation and usage errors to `2`, missing `get` to `3`, and filesystem failures to `1`;
- leaves stdout empty on every failure path.

- [ ] **Step 4: Run full verification**

Run:

```bash
bash -n bin/herdr-task-state tests/herdr_task_state_test.sh
if command -v shellcheck >/dev/null 2>&1; then
    shellcheck bin/herdr-task-state tests/herdr_task_state_test.sh
fi
jq -n -L lib 'include "herdr-task-state"; true'
./tests/herdr_task_state_test.sh
./tests/install_test.sh
git diff --check
```

Expected: syntax checks, jq import, both test suites, and whitespace validation all succeed.

- [ ] **Step 5: Commit hardening and test coverage**

```bash
git add bin/herdr-task-state tests/herdr_task_state_test.sh
git commit -m "test: harden Herdr task state storage" -m "Cover concurrent writers, private permissions, and failure preservation.\n\nGenerated-by: Codex"
```

---

### Task 5: User-facing contract and final verification

**Files:**
- Create: `docs/HERDR-TASK-STATE.md`
- Modify: `README.md`
- Modify: `tests/install_test.sh`

**Interfaces:**
- Consumes: the completed `bin/herdr-task-state` CLI and version 1 schema.
- Produces: a concise operator reference linked from README and an installation-contract assertion that the executable and jq module are present.

- [ ] **Step 1: Add failing repository contract assertions**

Extend `tests/install_test.sh` with paths for `bin/herdr-task-state`, `lib/herdr-task-state.jq`, and `docs/HERDR-TASK-STATE.md`. Add a test that asserts the executable exists and is executable, the jq module imports, and the documentation contains the default state path, `version`, `init`, `validate`, `get`, `put`, `remove`, exit statuses, and the prohibition on secrets.

- [ ] **Step 2: Run the installer test and verify it fails**

Run:

```bash
./tests/install_test.sh
```

Expected: FAIL because `docs/HERDR-TASK-STATE.md` does not exist and README has no task-state link.

- [ ] **Step 3: Write the operator documentation and README link**

Create `docs/HERDR-TASK-STATE.md` with:

- the stable task/workstream identity rules;
- the default and override state paths;
- the version 1 field table, separating stable identity from runtime references;
- exact CLI usage and exit status table;
- atomicity, locking, permissions, and no-secrets guarantees;
- a warning that callers must validate Herdr IDs against live state;
- examples that write only to a temporary override path, not the user's real state.

Add a short README subsection linking to this document. Keep full Space/Tab lifecycle tables out of this file because Issue #33 owns `docs/HERDR-WORK-MANAGEMENT.md`.

- [ ] **Step 4: Run final checks**

Run:

```bash
bash -n bin/herdr-task-state tests/herdr_task_state_test.sh tests/install_test.sh
if command -v shellcheck >/dev/null 2>&1; then
    shellcheck bin/herdr-task-state tests/herdr_task_state_test.sh tests/install_test.sh
fi
jq -n -L lib 'include "herdr-task-state"; true'
./tests/herdr_task_state_test.sh
./tests/install_test.sh
git diff --check
git status --short
```

Expected: every check exits `0`; status lists only the intended documentation and test changes for this task.

- [ ] **Step 5: Commit documentation**

```bash
git add README.md docs/HERDR-TASK-STATE.md tests/install_test.sh
git commit -m "docs: document Herdr task state storage" -m "Describe stable identities, CLI usage, and runtime-state safety guarantees.\n\nGenerated-by: Codex"
```

---

### Task 6: Branch verification and pull request

**Files:**
- Verify only; no planned file changes.

**Interfaces:**
- Consumes: all commits from Tasks 1–5.
- Produces: a pushed `feat/issue-31-herdr-task-state` branch and a Pull Request targeting `main` with review requested from `dodo5522`.

- [ ] **Step 1: Verify the complete branch**

Run:

```bash
bash -n bin/herdr-task-state tests/herdr_task_state_test.sh tests/install_test.sh
if command -v shellcheck >/dev/null 2>&1; then
    shellcheck bin/herdr-task-state tests/herdr_task_state_test.sh tests/install_test.sh
fi
jq -n -L lib 'include "herdr-task-state"; true'
./tests/herdr_task_state_test.sh
./tests/install_test.sh
git diff --check main...HEAD
git status --short --branch
git log --oneline main..HEAD
```

Expected: every check exits `0`, the worktree is clean, and all commits include the required `Generated-by: Codex` trailer.

- [ ] **Step 2: Inspect the final diff for scope and secrets**

Run:

```bash
git diff --stat main...HEAD
git diff --check main...HEAD
git diff --name-only main...HEAD
```

Expected files are limited to the design/plan, state CLI, jq module, tests, task-state documentation, and README. Confirm no token, credential, `.pem`, auth file, or real runtime state is present.

- [ ] **Step 3: Push the feature branch**

```bash
git push -u origin feat/issue-31-herdr-task-state
```

- [ ] **Step 4: Create the Pull Request**

Create a PR targeting `main`, reference `Closes #31`, summarize the JSON state and CLI contract, list exact verification commands, and request review from `dodo5522`. Do not merge it.

- [ ] **Step 5: Verify remote PR state**

Run:

```bash
gh pr view --json url,state,baseRefName,headRefName,reviewRequests
```

Expected: PR is open, base is `main`, head is `feat/issue-31-herdr-task-state`, and `dodo5522` is requested as reviewer.
