# Herdr Task State

This document is the operator reference for the versioned task-state store used
by the Herdr automation. It describes persistent identity and runtime
references only. It does not create, rename, focus, or delete Herdr resources.
The full resource lifecycle tables and operational rules belong to
[`HERDR-TASK-LIFECYCLE.md`](HERDR-TASK-LIFECYCLE.md). This state reference does
not repeat them.

## Stable identity

An Issue-backed task has the canonical key:

```text
<owner>/<repository>#<issue-number>
```

For example, `dodo5522/ai-agent-home#30` identifies one repository Issue. The
repository is lower-case GitHub `owner/name` form and matches
`^[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*$`. The Issue number is a positive
decimal integer without leading zeroes.

Every task has a `main` workstream. Optional parallel workstreams are lower-case
slugs matching `[a-z][a-z0-9-]{0,31}`. A workstream key is represented as
`<task-key>/<workstream>`. A Pull Request number is metadata on a workstream;
it is not part of either stable identity and may change.

Issue-less and PR-only identities are intentionally outside this version of the
contract.

## State location and schema

The default state path is:

```text
${XDG_STATE_HOME:-$HOME/.local/state}/ai-agent-home/herdr-tasks.json
```

Set `HERDR_TASK_STATE_FILE` to an absolute path to override it. The adjacent
`<state-path>.lock` file is used for coordination. State is runtime data and
must not be committed to Git.

Version 2 is an object with an integer `version`, a `tasks` map, and a
`persistent_agents` map. Each task map key is a stable task key. Required task
fields are `repository`, `issue_number`, and `workstreams.main`; the other
fields are optional until downstream resources exist. Version 1 files remain
readable. The first state mutation migrates them atomically to version 2 by
adding an empty `persistent_agents` map.

| Scope | Field | Meaning |
| --- | --- | --- |
| Document | `version` | Schema version; this document supports `2`. |
| Document | `tasks` | Map from stable task key to task object. |
| Document | `persistent_agents` | Exact-name mappings for long-lived Agents outside Issue tasks. |
| Stable identity | `repository` | Lower-case `owner/name`; must match the task key. |
| Stable identity | `issue_number` | Positive Issue number; must match the task key. |
| Stable identity | `workstreams.main` | Required primary workstream object. |
| Stable identity | workstream slug | `main` or a lower-case parallel-workstream slug. |
| Descriptive | `title` | Optional Issue title. |
| Runtime cleanup | `cleanup` | Optional resumable cleanup-progress record. |
| Runtime reference | `herdr.workspace_id` | Herdr workspace identifier, when known. |
| Runtime reference | `herdr.workspace_label` | Optional Herdr workspace label. |
| Runtime reference | `tab_id`, `tab_label` | Optional workstream Tab identifier and label. |
| Runtime reference | `pane_ids` | Optional role-to-pane identifier map. |
| Runtime reference | `agents` | Optional role-to-Agent name and exact Codex session ID map. |
| Runtime reference | `worktree`, `branch` | Optional absolute worktree path and branch name. |
| Runtime reference | `pull_requests` | Optional unique positive PR numbers. |

Runtime references are observations, not proof that a resource still exists or
belongs to this task. Before mutating anything, callers must validate Herdr IDs
against live Herdr state (and validate Git worktree and branch references with
Git). A stale identifier remains valid stored data until a reconciler decides
what to do with it.

`herdr-task start` is the current writer for the main workstream's worktree
and branch references. Its full validation, reconciliation, and managed
resource rules are defined in [`HERDR-TASK-LIFECYCLE.md`](HERDR-TASK-LIFECYCLE.md).

### Cleanup progress

`cleanup` is optional. When omitted, the task is active and no cleanup has
started. When present, it is a runtime record with these required fields:

| Field | Valid values | Meaning |
| --- | --- | --- |
| `task_root` | Absolute path | The resolved task root approved for this cleanup run. |
| `phase` | `pending`, `partial` | Cleanup has not yet completed, or stopped after recorded progress. |
| `completed_actions` | Set of `tab`, `worktree`, and `task_root` | Actions already completed or found absent. |
| `completed_targets` | Optional action-to-identifier sets | Individual targets completed or found absent within an unfinished action. |

Completed actions are serialized in lifecycle action order: `tab`, `worktree`,
then `task_root`; completed targets are serialized in the same action order with
sorted identifiers. The record must not use null values, duplicate action names,
or duplicate target identifiers. `partial` may have no completed action when the
first cleanup target failed. Lifecycle code deletes the cleanup record together
with the task mapping only after cleanup has completed. For the operational
cleanup, approval, and retry procedure, see
[`HERDR-TASK-LIFECYCLE.md`](HERDR-TASK-LIFECYCLE.md).

Unknown fields inside recognized objects are allowed for forward-compatible
metadata. Changing the meaning or type of an existing field requires a new
schema version and an explicit migration.

## CLI

The executable is `bin/herdr-task-state`, or the packaged command can be run
directly with `uvx --from ./tools/herdr_task_state herdr-task-state`. Use
`herdr-task-state --help` or `<command> --help` for operation descriptions and
argument formats. The command forms are:

```text
herdr-task-state init
herdr-task-state validate
herdr-task-state get TASK_KEY
herdr-task-state put TASK_KEY TASK_JSON_FILE
herdr-task-state remove TASK_KEY
```

Successful `validate`, `get`, `put`, and `remove` commands emit JSON on stdout.
`init` succeeds silently. Diagnostics are written to stderr, so callers may
safely capture stdout.

### Commands

- `init` succeeds silently and creates `{"version":2,"tasks":{},"persistent_agents":{}}`
  only when the state file is absent. If it exists, `init` validates it and
  leaves its content unchanged.
- `validate` validates the complete state file and emits the normalized
  document. It never modifies the file.
- `get` validates the key and complete state, then emits one task object. A
  missing task is a distinct not-found result.
- `put` reads exactly one task object from the named JSON file, validates its
  agreement with `<task-key>`, and atomically preserves unrelated tasks. It
  does not read standard input.
- `remove` removes exactly one task after validation. Removing an absent key is
  idempotent and succeeds. External lifecycle code must clean up resources
  before calling it.

### Exit statuses

| Status | Meaning |
| ---: | --- |
| `0` | Success. |
| `1` | Filesystem, locking, or unexpected runtime failure. |
| `2` | Usage error, invalid key/input, malformed state, or unsupported schema version. |
| `3` | `get` could not find the requested task. |

## Codex session mappings

An Issue Agent stores its session ID in the existing role entry under
`tasks.<task-key>.workstreams.<name>.agents`. A long-lived Agent stores the
same ID and its repository, Workspace, worktree, branch, and Pane binding in
`persistent_agents.<agent-name>`. Agent names and session IDs have one owner
across both maps.

On reconciliation, the binding must match exactly before a stored ID can be
used. The local Codex index and rollout file must both contain that exact ID.
A missing or malformed local session clears only its matching mapping and
starts one fresh Agent. A binding mismatch is retained and reported. A usable
mapping starts Codex with `resume <session-id>`; no recency-based resume option
is used. A resume error never falls back to a different fresh session. Cleanup
removes the nested Issue mapping together with its task mapping.

## Safety guarantees

Mutating commands take an exclusive `flock` on the adjacent lock file, read and
validate the complete current document, validate the candidate, write a
temporary file in the same directory, and atomically rename it over the state
file. Invalid input or candidate validation leaves the previous state intact.

The state directory is created with mode `0700`; state, lock, and temporary
files are private (`0600`), and the CLI runs with `umask 077`. Failed writes
remove only the exact temporary file created by that invocation.

Secrets, tokens, credentials, private keys, and authentication material are
prohibited from this schema and must never be stored in the task-state file.

## Safe examples

The examples below use a temporary override path. They do not read or modify
the user's real default state file.

```bash
task_state_dir=$(mktemp -d)
trap 'rm -rf "$task_state_dir"' EXIT
export HERDR_TASK_STATE_FILE="$task_state_dir/herdr-tasks.json"

bin/herdr-task-state init
bin/herdr-task-state validate
bin/herdr-task-state get dodo5522/ai-agent-home#30
bin/herdr-task-state remove dodo5522/ai-agent-home#30
```

To add a task, write one validated task object to a temporary JSON file and
pass that file to `put`:

```bash
task_json="$task_state_dir/task.json"
printf '%s\n' '{"repository":"dodo5522/ai-agent-home","issue_number":30,"workstreams":{"main":{}}}' >"$task_json"
bin/herdr-task-state put dodo5522/ai-agent-home#30 "$task_json"
```
