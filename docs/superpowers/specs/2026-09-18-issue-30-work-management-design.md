# Issue #30 Work Management Design

## Goal

Make `herdr-task start` register one Issue's existing, managed Git worktree
and branch together with its repository Workspace, Issue Tab, and root Pane.
The resulting state lets an operator trace the active Issue Tab to its
worktree and branch without extending the separate Agent, reviewer, or PR
automation responsibilities.

## Scope

This design extends the existing `herdr-task start ISSUE_NUMBER --cwd PATH`
workflow. Before creating or reusing any Herdr resource, the command will:

1. Resolve `PATH` to an existing directory and Git worktree.
2. Read `git worktree list --porcelain` from the repository and find the
   record whose worktree path equals the resolved `PATH`.
3. Reject the repository's primary worktree, a detached HEAD, and a worktree
   without a local branch.
4. Find a direct `.codex-task-root` marker in an ancestor of the worktree,
   require that marker directory to be strictly below
   `/home/takashi/work/tasks/`, and require the worktree to be beneath that
   marker directory.
5. Record the resolved absolute worktree path and branch in the task's `main`
   workstream atomically with the Herdr Workspace, Tab, and root-Pane IDs.

The command will continue to resolve the repository from the `origin` remote,
load the Issue title, use state-recorded Herdr IDs only after live validation,
and create background resources with `--no-focus`.

## State and reconciliation rules

The main workstream's `worktree` and `branch` fields are the authoritative
runtime references for this command after its first successful registration.

- A legacy task that has no `worktree` or `branch` may be upgraded by a valid
  `start` invocation.
- Re-running `start` from the same registered worktree and branch reuses the
  existing managed Workspace and Tab and leaves unrelated workstreams and
  metadata unchanged.
- Re-running from a different worktree or branch for an already registered
  main workstream fails without changing state or Herdr resources. Parallel
  workstreams are deliberately outside this command's scope.
- A stored worktree that is no longer registered with Git, or whose checked
  out branch no longer matches the recorded branch, causes a safe failure.
  The operator must resolve that inconsistency explicitly rather than letting
  `start` adopt a replacement path.

The implementation must validate the worktree before creating a Workspace or
Tab. If later Herdr creation or state persistence fails, it retains the
existing rollback rule: close only a Workspace or Tab created by that
invocation, never a state-owned or unmanaged resource.

## Labels and managed boundaries

The primary Issue Tab label is exactly:

```text
#<issue-number> <short-title>
```

The `#` is a human-facing label requirement. State identity remains the
unchanged `owner/repository#issue-number` key, so a label never proves
ownership. A managed Workspace label remains the normalized
`owner/repository` value.

`start` must not adopt, rename, move, or delete a label-matched unmanaged
Workspace, Tab, Pane, or worktree. It does not create Git worktrees; the
caller creates the feature worktree beneath its marked task root before
calling `start`.

## Explicitly deferred responsibilities

Issue #30 provides the management layer only. It does not implement the
underlying responsibilities of the related open Issues:

| Responsibility | Deferred to |
| --- | --- |
| Starting, naming, and recovering Agents | #9 |
| Recording and restoring Codex sessions | #10 |
| Creating and removing Git worktrees | #11 |
| Reviewer Agent workflow | #12 |
| Adding role Panes or attaching PR metadata | Reserved `herdr-task pane` and `herdr-task pr` namespaces |

The existing state fields for Agents, session IDs, PR numbers, and additional
Pane roles remain forward-compatible metadata. This change neither creates
nor mutates those fields.

## Error behavior

The command reports a concise lifecycle error and makes no state or Herdr
resource mutation when the cwd is not a registered non-primary worktree, is
detached, lacks a branch, has no valid task-root marker, is outside the task
root boundary, or conflicts with an existing main-workstream registration.
Command diagnostics must not expose GitHub credentials or raw command output.

## Verification

Tests will exercise the real state model and a controlled Git/Herdr boundary
fake. They will prove that a valid worktree persists its absolute path and
branch, a second run reuses the stored resources, and every invalid or
conflicting worktree condition leaves state and Herdr inventory unchanged.
Existing cleanup tests will continue to prove that the stored worktree is
eligible for the guarded plan-and-approval cleanup lifecycle.

Documentation will make the required order explicit: create a feature
worktree under a marked task root, then run `herdr-task start` from that
worktree. It will also align the displayed Tab-label format with the
decision recorded for Issue #30.
