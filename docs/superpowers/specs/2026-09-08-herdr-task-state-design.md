# Herdr Task State and Stable Identity Design

## Scope

Issue #31 provides the persistent state foundation used by the later Space/Tab reconciler and lifecycle automation. It does not create, rename, focus, or delete Herdr resources. It also does not create worktrees, start agents, or query GitHub.

The feature owns four responsibilities:

1. Derive and validate stable task and workstream keys from already-resolved inputs.
2. Store task mappings in one versioned JSON document.
3. Read and update that document without lost updates or partial writes.
4. Expose a small shell CLI that later scripts can call and test independently.

## Identity model

An Issue-backed task uses this canonical key:

```text
<owner>/<repository>#<issue-number>
```

Example:

```text
dodo5522/ai-agent-home#30
```

The repository identifier is lower-case and uses the GitHub `owner/name` form. It matches `^[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*$`; exactly one slash separates owner and repository. The Issue number is a positive decimal integer without leading zeroes. Callers normalize a GitHub remote to this form before invoking the state CLI.

Every task contains a `main` workstream. Optional parallel workstreams use a lower-case slug matching `[a-z][a-z0-9-]{0,31}`. A workstream does not use a Pull Request number as its identity. A fully qualified workstream key is represented externally as:

```text
<task-key>/<workstream>
```

Pull Request numbers are metadata attached to a workstream and can change without changing either stable key.

Issue-less tasks and PR-only tasks are intentionally deferred. Supporting them before their lifecycle is defined would weaken the identity contract needed by Issue #30.

## State location and permissions

The default state file is:

```text
${XDG_STATE_HOME:-$HOME/.local/state}/ai-agent-home/herdr-tasks.json
```

Tests and callers may override it with `HERDR_TASK_STATE_FILE`. The implementation creates the parent directory with mode `0700`, runs with `umask 077`, and keeps the state and lock files private to the user. The state file is runtime data and is never added to Git.

The adjacent lock file is `<state-file>.lock`. Locking the separate file is important because the state file itself is replaced during an atomic update.

Secrets, tokens, credentials, private keys, and authentication material are outside the schema and must never be stored in this file.

## Version 1 schema

The top-level document is an object with an integer version and a task map:

```json
{
  "version": 1,
  "tasks": {
    "dodo5522/ai-agent-home#30": {
      "repository": "dodo5522/ai-agent-home",
      "issue_number": 30,
      "title": "リポジトリ / Issue 単位で Herdr Space・Tab を自動管理する",
      "herdr": {
        "workspace_id": "wJ",
        "workspace_label": "ai-agent-home"
      },
      "workstreams": {
        "main": {
          "tab_id": "wJ:t5",
          "tab_label": "#30 Herdr作業管理",
          "pane_ids": {
            "implementer": "wJ:p5"
          },
          "worktree": "/home/takashi/work/tasks/issue-30/worktree",
          "branch": "feat/issue-30-herdr-layout",
          "pull_requests": [42],
          "agents": {
            "implementer": {
              "name": "aah-30-impl",
              "codex_session_id": "01a076e0-7448-75d0-8336-88b91ba5bfc1"
            }
          }
        }
      }
    }
  }
}
```

Required fields for each task are `repository`, `issue_number`, and `workstreams.main`. `title`, `herdr`, and all runtime mappings within a workstream are optional because state is created before every downstream resource necessarily exists.

When present:

- `repository` must equal the repository portion of the task key.
- `issue_number` must equal the Issue portion of the task key.
- `workstreams` must be an object with unique valid workstream slugs and a `main` object.
- `pull_requests` is an array of unique positive integers.
- `pane_ids` and `agents` are maps keyed by a valid role slug.
- `worktree` is an absolute path.
- IDs, labels, branch names, titles, Agent names, and session IDs are non-empty strings.

The `herdr` and workstream runtime fields are references, not proof that a resource still exists or belongs to the task. Later reconcilers must validate them against current Herdr and Git state before mutation.

Version 1 rejects an absent, non-integer, or unsupported top-level `version`. Unknown fields are permitted within recognized objects so later issues can add metadata without forcing an immediate schema version change. Changing the meaning or type of an existing field requires a new version and explicit migration.

## CLI contract

The implementation adds `bin/herdr-task-state` with these commands:

```text
herdr-task-state init
herdr-task-state validate
herdr-task-state get <task-key>
herdr-task-state put <task-key> <task-json-file>
herdr-task-state remove <task-key>
```

All successful read commands emit JSON on stdout. Logs and errors go to stderr so callers can safely capture stdout.

### `init`

Creates `{"version":1,"tasks":{}}` only when the state file does not exist. If it already exists, it validates the document and leaves it byte-for-byte unchanged.

### `validate`

Validates the complete state file and emits the normalized document. It never modifies the file.

### `get`

Validates the key and complete document, then emits the matching task object. A missing task is a distinct not-found result rather than malformed state.

### `put`

Reads one task object from the named file. Standard input is not used so an empty or truncated pipeline cannot accidentally become a valid update. It validates both the input object and its agreement with `<task-key>`, then performs a locked read-modify-write. Existing unrelated tasks are preserved.

### `remove`

Removes exactly one task after a locked read and validation. Removing an absent key is idempotent and succeeds without changing the file. This primitive only updates state; lifecycle code remains responsible for proving that external resources were cleaned up first.

### Exit status

- `0`: success
- `2`: CLI usage error, invalid key, invalid input, malformed state, or unsupported schema version
- `3`: requested task was not found by `get`
- `1`: filesystem, locking, or unexpected runtime failure

## Atomic update algorithm

Every mutating command follows the same sequence:

1. Resolve explicit absolute paths without using a broad or unresolved deletion target.
2. Create the state directory if needed and open the adjacent lock file.
3. Acquire an exclusive `flock` before reading current state.
4. Read and validate the complete current document, or initialize an in-memory empty version 1 document when no file exists.
5. Apply exactly one task mutation using `jq` arguments rather than string-built filters.
6. Validate the complete candidate document.
7. Write the candidate to a temporary file in the same directory.
8. Set the temporary file mode to `0600`.
9. Atomically rename it over the destination.
10. Release the lock after the rename completes.

A trap removes only the exact temporary file created by that invocation. Invalid input, invalid existing state, or a failed candidate validation leaves the prior state untouched. No recovery path silently replaces malformed state with an empty document.

## Error handling

Errors name the failed operation and state path but do not print the full state document. Validation errors identify the task key and field where practical. The CLI does not log Agent session IDs or arbitrary metadata values.

An unsupported schema version stops all reads and writes. A stale Herdr ID remains valid JSON and is not removed by this layer; deciding whether it is stale belongs to the reconciler in the next child Issue.

## Testing

`tests/herdr_task_state_test.sh` uses a unique temporary directory and overrides `HERDR_TASK_STATE_FILE`. It covers:

- first initialization and idempotent repeated initialization;
- default permissions for the directory and file;
- valid `put` and `get` round trips;
- preservation of unrelated task entries;
- idempotent removal;
- distinct not-found status;
- invalid task keys and workstream slugs;
- mismatch between the map key, repository, and Issue number;
- malformed JSON, missing required fields, and unsupported versions;
- rejection of relative worktree paths and invalid PR lists;
- invalid updates leaving the previous file unchanged;
- concurrent writers preserving all successfully written tasks;
- stdout containing JSON only and diagnostics using stderr;
- shell syntax and, when installed, ShellCheck.

The existing installer test remains unchanged except for any assertion needed to document or install the new executable. Tests do not inspect or modify the real user state file.

## Integration boundaries

- Issue #32 calls this CLI to resolve and persist Space/Tab reconciliation results.
- Issue #9 may store task-scoped Agent names but retains ownership of Agent startup and recovery.
- Issue #10 may store Codex session IDs but retains ownership of session discovery and resume behavior.
- Issue #11 may store worktree and branch mappings but retains ownership of Git worktree lifecycle.
- Issue #33 calls `remove` only after its external cleanup checks and human approval have succeeded.

This separation keeps state persistence deterministic and testable without a running Herdr server, a GitHub token, a Git repository, or a Codex process.
