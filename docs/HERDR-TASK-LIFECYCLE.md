# Herdr Task Lifecycle

This document is the sole operational source of truth for Herdr-managed Issue
tasks, from `herdr-task start` through approved cleanup. The low-level state
schema and state-only CLI are documented in
[`HERDR-TASK-STATE.md`](HERDR-TASK-STATE.md).

The current `herdr-task` release implements only `start` and `cleanup`. The
`pr` and `pane` namespaces described below reserve future command boundaries;
they are not implemented commands and must not be invoked.

## Identity and resource model

An Issue-backed task has the stable key `owner/name#issue-number`. Every task
has a `main` workstream. A parallel workstream, when needed, has the stable key
`owner/name#issue-number/workstream`, where `workstream` is a lower-case slug.
A Pull Request number is metadata on a workstream and never replaces either
stable key.

| Resource | Role and identifier | Label or metadata | cwd |
| --- | --- | --- | --- |
| Workspace | One repository container; stored Herdr workspace ID. | `owner/name` | Repository or Issue worktree passed to `start`. |
| Main Tab | Primary Issue workstream; stored Herdr Tab ID. | `<issue-number> <short-title>` | The resolved `start --cwd` path. |
| Parallel Tab | Independent future workstream; stored Herdr Tab ID. | `#<issue-number>/<workstream> <short-title>` | That workstream's registered worktree. |
| Pane | One concurrent role in a Tab; stored by role to Herdr Pane ID. | Initial role key `root`; future roles include `implementer`, `reviewer`, `shell`, `test`, `server`, and `logs`. | The Tab worktree unless that role explicitly needs another path. |
| Agent | One top-level Agent per Agent Pane; stored by role with its unique Agent name and optional Codex session ID. | A task-unique name plus the role; no global naming format is implemented yet. | Inherits its Pane cwd. |
| Worktree | One registered non-primary Git worktree per active workstream; stored as an absolute path with its branch. | Branch metadata belongs to the workstream. | The worktree path itself. |
| Task root | Container for one Issue's managed worktrees and artifacts; identified by its resolved absolute path and direct `.codex-task-root` file. | Directory name is descriptive, not ownership proof. | Not a command cwd; all worktree paths must resolve to this one root. |
| Pull Request | Positive PR number attached to a workstream. | One workstream may hold multiple unique PR numbers and future status metadata. | Does not change cwd, task identity, or Tab identity. |

## Lifecycle triggers

| Event | Required behavior |
| --- | --- |
| Issue work starts | Run `bin/herdr-task start ISSUE`; create or reuse the state-recorded repository Workspace and main Issue Tab. |
| Independent workstream becomes necessary | Future `pane`/workstream support may add one parallel Tab and worktree. Do not create one merely for another process in the same workstream. |
| Concurrent reviewer, server, logs, shell, or test role becomes necessary | Future `pane` support may add a role Pane to the existing Tab. Keep one top-level Agent per Agent Pane. |
| PR opens or remains under review | Keep the same Issue task, Tab, worktree, task root, and state mapping. PR metadata is attached to its workstream; it does not start a replacement task. |
| User reports a PR merged | Switch to `main`, pull `origin/main` with `--ff-only`, verify synchronization, then begin the cleanup plan and approval process below. |
| Work has no PR | Begin cleanup only after the user explicitly confirms the work is complete. |
| Cleanup is partial | Keep the state mapping and recorded progress, correct the blocker, and follow the retry process below. |

## Managed and unmanaged boundaries

A Workspace is a repository-wide managed resource shared by tasks in the same
repository. `start` may reuse its stored ID from any same-repository task only
after the live Workspace label matches that repository. All other resources
are task- or workstream-scoped and are eligible for managed operations only
when their exact identifiers are recorded on the current task. Before a
mutation, the CLI validates that the stored identifier still names the
expected live resource; an exact target that is no longer live may be reported
as `already_absent`. Labels, directory names, display order, and matching cwd
values are descriptive; they never prove ownership.

`start` may reuse or modify only state-recorded Workspace and Tab IDs. If a
stored ID is stale, it creates a replacement managed resource without adopting,
renaming, moving, or deleting a label-matched unmanaged resource. A resource
created manually or absent from state remains unmanaged even when its label
looks identical. A resource recorded only for another task cannot be adopted,
except for the validated same-repository Workspace described above.

`cleanup` considers only the current task's state-recorded Tabs and worktrees
and their one validated task root. It never closes the repository Workspace,
deletes an unmanaged Herdr resource, removes a primary checkout, or removes a
different task's data.

## Starting an Issue task

Run from a Herdr-managed Pane:

```bash
bin/herdr-task start 32
```

To resolve another repository or Issue-worktree directory, supply it explicitly:

```bash
bin/herdr-task start 32 --cwd /absolute/path/to/repository
```

`start` requires `HERDR_ENV=1`. It resolves the lower-case `owner/name` from
the Git `origin`, loads the Issue title through GitHub CLI JSON, and uses a
configured GitHub App token when the caller has no `GH_TOKEN`. Token material
and raw command output are never included in diagnostics.

The command creates or reuses resources by stored ID, uses `--no-focus` for
background creation, validates that the managed Tab has exactly one initial
root Pane, and atomically records the successful IDs. A failed invocation
rolls back only resources it created during that invocation and preserves
previously managed resources. Re-running `start` reconciles the same task
without creating duplicate resources. Read-only `herdr-task-state` operations
never create Herdr resources.

## Planning and approving cleanup

Cleanup is always a plan, human approval, then execution process. From the
task repository, first create a read-only plan:

```bash
bin/herdr-task cleanup 32 --plan
```

The JSON response contains `task_key`, the resolved `task_root`, and ordered
`tab`, `worktree`, and `task_root` actions. Planning does not create, close,
rename, remove, or write any resource.

| Outcome | Meaning | Operator response |
| --- | --- | --- |
| `delete` | The state-recorded target still matches the validated live resource. | Review the exact target as proposed destructive work. |
| `already_absent` | The managed target is no longer live. | No destructive operation is needed; execution records completion. |
| `blocked` | Ownership, live identity, path safety, or inventory cannot be proven. | Do not execute. Resolve the mismatch and run a new plan. |

Show the complete JSON preview to the human. Confirm that the task key is the
intended Issue, every target belongs to it, there are no `blocked` actions,
and the task root is the expected exact absolute path. Ask for explicit
approval to attempt cleanup for that task and exact root under the validated
managed-resource boundaries.

The current CLI does not bind execution to the previously displayed plan:
there is no plan digest or plan input on `--execute`. Instead, `--execute`
builds a fresh plan in its own invocation and `--confirm-task-root` binds only
the exact resolved root. Run `--plan` immediately before requesting approval
and executing, and avoid intervening state or resource changes. Any newly
displayed preview is a fresh plan and requires fresh approval. If approval
must be bound to an immutable plan digest, do not use `--execute` in this
release.

Only after approval, copy the exact `task_root` value into the guarded command:

```bash
bin/herdr-task cleanup 32 --execute \
  --confirm-task-root /home/takashi/work/tasks/issue-32-example
```

The confirmation must be an absolute, already-resolved path that exactly
matches the fresh execution plan's root. Execution rejects a `blocked` plan,
then revalidates the fresh plan and its exact targets before mutations. It does
not compare that plan with the previously displayed preview.

Execution proceeds in this order:

1. Close each validated managed Issue Tab. Closing its Tab owns Pane cleanup;
   the repository Workspace remains open.
2. Remove each validated registered non-primary Issue worktree through Git.
3. Recursively remove the single approved task root only when it is strictly
   below `/home/takashi/work/tasks/`, has a direct regular
   `.codex-task-root`, and contains no other registered or unmanaged Git
   worktree.
4. Remove the task state mapping only after every earlier action completed or
   was already absent.

## Retrying partial cleanup

Progress is written before destructive work and after each completed or
already-absent target. If an action fails, the task mapping remains with
`partial` cleanup progress; do not remove or rewrite it manually.

1. Inspect the failure and correct only the reported blocker or stale external
   condition.
2. Run `bin/herdr-task cleanup ISSUE --plan` again. The new plan revalidates
   live state and lists the remaining work.
3. Show the new complete plan to the human and obtain fresh approval.
4. Re-run `--execute --confirm-task-root EXACT_PATH`. Completed targets are
   verified as absent and are not deleted twice.

Repeat this sequence after every partial failure. Never skip the new plan or
reuse approval when its targets or resolved root have changed.

## Reserved future command boundaries

`herdr-task pr` is reserved for attaching and updating Pull Request numbers
and status metadata on existing workstreams. It must preserve the Issue task
key, Tab, worktree, task root, and cleanup boundary. No `pr` subcommand exists
in the current release.

`herdr-task pane` is reserved for adding or reconciling role Panes and their
Agents only when concurrent work requires them. It must derive ownership from
state-recorded IDs, create in the workstream Tab with `--no-focus`, and keep one
top-level Agent per Agent Pane. No `pane` subcommand exists in the current
release.
