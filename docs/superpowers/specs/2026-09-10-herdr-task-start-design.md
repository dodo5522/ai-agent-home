# Herdr Task Start and Space/Tab Reconciliation Design

## Scope

Issue #32 adds the command used when implementation of an Issue begins. It
resolves the repository and Issue identity, obtains the Issue title, reconciles
managed Herdr resources, and records the resulting runtime references in the
existing task-state document.

The existing task-state models and storage remain the source of truth for the
JSON schema, validation, locking, and atomic writes. This feature does not
start Agents, create Git worktrees, resume Codex sessions, or perform lifecycle
cleanup; those responsibilities remain with Issues #9, #10, #11, and #33.

## Command interface

The packaged command is:

```text
herdr-task-start ISSUE_NUMBER [--cwd PATH]
```

`ISSUE_NUMBER` is a positive decimal Issue number. `--cwd` defaults to the
current directory and identifies both the Git repository and the cwd supplied
to newly created Herdr panes. It is useful when the command is started from an
Issue worktree. The command requires `HERDR_ENV=1`; it never creates resources
for read-only task-state operations such as `herdr-task-state get` or
`validate`.

The repository is resolved from the `origin` Git remote in `--cwd`. Supported
GitHub HTTPS and SSH remote forms are normalized to lower-case `owner/name`.
The title is read with:

```text
gh issue view ISSUE_NUMBER --repo owner/name --json title
```

Command execution uses argument arrays and parses JSON responses strictly;
shell interpolation is not used.

## Resource ownership and identity

The task-state document is the ownership record for resources managed by this
command. A workspace or tab is eligible for reuse only when its ID is already
stored in a task for the same repository (workspace) or in the target task
(tab), and the live Herdr object passes all identity checks. A live object that
merely has the expected label is not imported. This keeps unmanaged user
resources untouched, even when their labels happen to match.

Managed labels are deterministic:

* Workspace label: `owner/name`.
* Tab label: `<issue-number> <short-title>`.

`short-title` collapses runs of whitespace and truncates to a fixed 60-character
display name, appending `…` when truncation is needed. The stable task key is
always `owner/name#issue-number`; labels are presentation only.

## Reconciliation flow

1. Parse and validate the Issue number, check `HERDR_ENV`, resolve the GitHub
   repository, and fetch the Issue title.
2. Read the current state and locate live managed workspace IDs for the same
   repository. Validate each candidate using `herdr workspace get`, including
   its workspace label. If exactly one candidate is valid, reuse it.
3. If no managed candidate is valid, create a workspace with the repository
   label, `--cwd`, and `--no-focus`. The create response supplies the opaque
   workspace, tab, and root-pane IDs. The newly created tab is renamed to the
   managed Issue label; only resources created by this invocation may be
   changed.
4. For the target task, validate its stored tab ID with `herdr tab get`, its
   workspace membership, its exact label, and that its tab contains exactly one
   pane. If any check fails or no tab is stored, create a tab with the expected
   label, workspace, cwd, and `--no-focus`. A tab created as part of a new
   workspace is reused after its label is set.
5. Validate the selected root pane. The pane must belong to the selected tab,
   and the live pane list must contain exactly one pane for that tab. The
   command never splits, moves, renames, or deletes an existing unmanaged pane.
6. Construct or update the target `Task`, preserving descriptive fields and
   unrelated workstream metadata while replacing only the current Herdr
   workspace/tab/pane references. Persist it with the existing atomic
   `StateStore` operation only after all Herdr checks succeed.

If a stored ID is stale or its live object has the wrong identity, the command
creates a replacement and leaves the stale object untouched. If a Herdr or
GitHub operation fails, the state file is not updated and the command exits
with a runtime error. Newly created managed resources are tracked for
best-effort rollback on a later failure; rollback never targets resources that
predated this invocation.

## Error handling and safety

* Invalid Issue numbers, malformed remotes, invalid JSON, and identity
  mismatches are usage/validation failures.
* Missing `HERDR_ENV`, unavailable `gh`/`herdr`, non-zero command responses, and
  malformed Herdr JSON are runtime failures.
* stdout contains one machine-readable success document only. Diagnostics are
  written to stderr and do not echo arbitrary state, titles, or session IDs.
* `--no-focus` is passed to every background workspace/tab creation command.
* Existing unmanaged workspaces, tabs, and panes are never renamed, moved,
  deleted, or added to task state.

## Implementation boundaries

The feature lives in the existing `tools/herdr_task_state` project so it can
reuse the Pydantic models and `StateStore` without duplicating the schema. Add
a focused reconciliation module and a `herdr-task-start` console entry point;
keep `model.py` and `store.py` independent of GitHub and Herdr subprocesses.
The `bin/herdr-task-start` script is a thin uv-managed launcher like the
existing task-state wrapper.

The Herdr and GitHub command clients receive an injectable command runner so
unit tests can use temporary fake executables. Production code uses only the
Python standard library in addition to the existing Pydantic dependency.

## Testing strategy

Pytest fixtures create temporary state files, fake `gh` and `herdr` binaries,
and controlled Git repositories. Tests cover:

* repository and Issue/title resolution;
* first-run workspace and tab creation with JSON-derived IDs, cwd, and
  `--no-focus`;
* sequential reruns reusing the same managed IDs without duplicate creates;
* stale state IDs producing replacements;
* exact one-root-pane validation;
* unmanaged same-label resources remaining untouched and unimported;
* Herdr/GitHub failures and partial failures leaving state unchanged;
* normalized labels, preserved task metadata, and strict command output.

Existing task-state and installer tests remain green, and Ruff formatting/lint
checks continue to apply to all Python sources.
