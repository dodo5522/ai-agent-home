# Issue #10 Codex Session Mapping Design

## Goal

Resume every managed Herdr Codex Agent into its recorded Codex session after
an Agent or host restart. The existing Herdr task-state JSON remains the single
source of persisted automation state. Each session is bound to its Agent,
repository, Herdr Workspace, Git worktree, and branch so reconciliation cannot
resume a conversation in another project or task.

## Scope

This change implements a version 2 state document with session storage, an
atomic version 1 migration, discovery of the exact session ID reported by
Herdr, explicit `codex resume SESSION_ID` startup, safe fresh-session fallback,
stale mapping handling, and multi-Agent restart tests.

It does not add another state file, continuously supervise Agents, create
worktrees, dispatch coordinator requests, add reviewer Panes, or select models.
Automation never selects a session by recency and must not use
`codex resume --last --all`.

## One state document

The state path remains:

```text
${XDG_STATE_HOME:-$HOME/.local/state}/ai-agent-home/herdr-tasks.json
```

Issue Agents use the existing optional field at
`tasks.<task-key>.workstreams.<workstream>.agents.<role>.codex_session_id`.
Their repository, Workspace, worktree, branch, Pane, and Agent bindings already
exist in surrounding objects and are not duplicated.

Persistent Agents have no Issue task. Version 2 adds a required top-level
`persistent_agents` map keyed by exact managed Agent name; the map may be empty.
Each value contains
the non-empty `codex_session_id`, normalized `repository`, `workspace_id`,
`workspace_label`, resolved absolute `worktree`, attached `branch`, and the last
validated `pane_id`.

```json
{
  "version": 2,
  "tasks": {
    "dodo5522/ai-agent-home#10": {
      "repository": "dodo5522/ai-agent-home",
      "issue_number": 10,
      "herdr": {
        "workspace_id": "w1C",
        "workspace_label": "dodo5522/ai-agent-home"
      },
      "workstreams": {
        "main": {
          "worktree": "/work/takashi/tasks/issue-10/worktree",
          "branch": "feat/issue-10-session-mapping",
          "pane_ids": {"root": "w1C:p1"},
          "agents": {
            "implementer": {
              "name": "codex-issue-10-0e555c32",
              "codex_session_id": "01a0c85f-f7a4-7ca3-9b4b-6c1e2f02fd4a"
            }
          }
        }
      }
    }
  },
  "persistent_agents": {
    "codex-coordinator": {
      "codex_session_id": "01b10000-0000-7000-8000-000000000000",
      "repository": "dodo5522/ai-agent-home",
      "workspace_id": "w1",
      "workspace_label": "dodo5522/ai-agent-home",
      "worktree": "/home/takashi",
      "branch": "main",
      "pane_id": "w1:p1"
    }
  }
}
```

The schema advances to version 2 because `persistent_agents` introduces a new
managed resource class and document-wide uniqueness rules that version 1 code
cannot validate. Version 2 requires `persistent_agents`, although it may be an
empty map. The existing Issue task shape and optional Issue session field keep
their meanings.

Version 1 remains a supported migration input. Migration validates the complete
version 1 document, preserves `tasks` and unknown forward-compatible fields,
adds an empty `persistent_agents` map, changes `version` to `2`, validates the
result, and atomically replaces the same file under its existing lock. A failed
migration leaves the original bytes intact. Migrating version 2 is an
idempotent no-op; other versions are rejected.

Read-only validation accepts versions 1 and 2 without writing. A newly
initialized state uses version 2. The first mutating operation on valid version
1 state performs the migration in the same lock scope before applying its
requested change. This avoids a separate operator migration window while still
making the schema transition explicit and testable. Once written as version 2,
the existing version 1 binary rejects the document instead of updating state
without enforcing the new cross-Agent invariants.

The existing state lock, private permissions, strict parsing, whole-document
validation, atomic replace, and temporary-file cleanup apply to every session
update. No cross-file transaction or session mirror exists. State contains
identifiers and paths only; credentials, prompts, transcripts, and token
material are prohibited.

## State invariants and operations

The model validates mappings across both locations:

- Agent names are non-empty and unique among task and persistent entries.
- A Codex session ID belongs to at most one Agent.
- An Issue session requires its surrounding repository, Workspace, worktree,
  branch, Pane role, and Agent references.
- A persistent mapping requires every binding field listed above.
- Optional values are omitted; null values are rejected.

`herdr_task_state` gains lock-scoped operations to find an Agent by exact name,
compare its binding, update its observed session, or remove its mapping without
overwriting unrelated state. Updating an Issue Agent changes only
`codex_session_id`; removal retains the Agent name and task resources. Removing
a persistent mapping removes its `persistent_agents` entry because its binding
is reconstructed from configuration and validated live resources.

The state CLI exposes read-only session listing and exact-name session removal
for resolving a reported binding conflict. Removal changes only the mapping,
never Codex session files, Herdr resources, task resources, or another Agent.
Ordinary missing-session fallback needs no operator action.

## Ownership and package boundaries

`herdr_runtime` decodes the optional session identity exposed by Herdr and
passes explicit native arguments to `herdr agent start`.

`herdr_task_state` owns the document's session models, validation, locking, and
atomic updates. `herdr_agents` owns binding comparison and the generic
start-or-resume decision, consuming state through a focused protocol.
Persistent reconciliation writes `persistent_agents`; Issue lifecycle writes
the existing task Agent reference. `herdr_task_lifecycle` retains Issue policy,
initial prompting, and cleanup behavior.

The dependency direction becomes:

```text
herdr_task_lifecycle -> herdr_agents -> herdr_runtime
                     -> herdr_task_state <- herdr_agents
```

## Binding identity

Every reconciliation supplies an exact Agent name, Pane ID, Workspace ID and
label, repository, resolved worktree, and attached branch. Persistent Agent
definitions retain their Workspace label and cwd; the resolver derives the
repository from normalized Git `origin` and the branch from Git. A cwd that is
not an attached worktree root, has no branch, or belongs to another repository
fails before startup. Issue lifecycle supplies the same identity from its
validated origin and stored task resources.

Repository, Workspace ID and label, worktree, and branch must match before a
session is resumed. Pane ID is placement rather than stable ownership: a
managed Pane may be recreated without changing the worktree or session. A
successful reconciliation records the current persistent Pane; Issue state
already records its Pane by role.

## Reconciliation flow

For each exact managed Agent name:

1. Resolve and validate the complete target binding.
2. Read the exact mapping from the locked state document.
3. Find the exact live Agent.
4. If live, validate Pane, Workspace, cwd, kind, and reported session ID, then
   store that observation. A live Agent is authoritative only after placement
   checks pass.
5. If absent with no stored session, start fresh on the exact Pane, read the
   reported session ID, and persist it.
6. If absent with a matching binding, start with native arguments
   `resume SESSION_ID`, require Herdr to report the same ID, and refresh state.
7. If resume proves the session absent or unreadable, clear only that mapping,
   wait for the exact Pane to become an available shell, start fresh once, and
   store the new ID.
8. Return whether the Agent was reused, resumed, or freshly started. Issue
   lifecycle sends its initial prompt only for a fresh session.

Herdr startup must distinguish a blocked or running Agent from a process that
exited because its session could not load. Only the latter triggers fallback.
Authentication failures, approval prompts, live-process timeouts, unavailable
Panes, and unknown errors remain failures and never start a second Agent.

## Stale and conflicting mappings

- A missing session starts fresh and records the observed ID.
- A matching binding with a conclusively absent or unreadable session falls
  back once and replaces the ID.
- A binding mismatch is reported and is not resumed, cleared, or replaced.
- A session ID owned by another Agent is a conflict even if it appears old.
- A correctly placed live exact-name Agent with a different session may update
  its mapping only when that ID is unclaimed.
- A live Agent without a reported session ID is not written to state.

Diagnostics may include Agent names, IDs, paths, and branches, but never raw
subprocess output that could contain credentials.

## Bootstrap, cleanup, and failure isolation

Bootstrap still waits for Herdr and runs `herdr-agents reconcile`. Persistent
definitions are reconciled independently, so one failure does not prevent later
Agents from restoring.

`herdr-task start` persists Workspace, Tab, Pane, worktree, and branch before
Agent reconciliation. A session failure retains those resources and its prior
session value for inspection and retry. Successful Issue cleanup already
removes the whole task entry, so its nested mapping disappears in that atomic
update without a new cleanup action. Persistent mappings remain outside Issue
cleanup ownership.

## Testing

Tests prove:

- version 1 validation is read-only, and its first mutation migrates atomically
  to version 2 without changing existing tasks or unknown fields;
- failed migration preserves the original version 1 bytes, repeated version 2
  migration is a no-op, and unsupported versions are rejected;
- persistent mapping validation, private permissions, atomic updates, locking,
  and preservation of unrelated state;
- duplicate Agent names and session ownership across both locations fail;
- Herdr decodes present, absent, and malformed session identities;
- fresh startup has no recency option and exact resume uses
  `resume SESSION_ID` on the requested Pane;
- binding conflicts fail without mutation;
- only a conclusively missing or corrupt session falls back once;
- resumed Issue Agents receive no duplicate initial prompt;
- exact task and persistent mappings update independently; and
- one persistent Agent failure does not prevent another from restoring.

An isolated reboot-style test creates at least two managed Codex Agents with
different repository/worktree bindings, captures distinct session IDs, restarts
the test Herdr session/bootstrap, and verifies that each returns on its recorded
Pane with the same ID. A negative case changes one binding and verifies no
session resumes in the wrong project. It uses a named isolated Herdr session
and temporary state and never stops or mutates the active operator session.

Before publication, run Ruff and pytest for `herdr_runtime`, `herdr_agents`,
`herdr_task_state`, and `herdr_task_lifecycle`, then the isolated restart test
when the installed Herdr/Codex environment supports it.

## Documentation updates

Update `docs/HERDR-TASK-STATE.md` with the version 2 persistent Agent map, v1
migration, existing nested Issue session field, uniqueness rules, and session
CLI. Update `docs/HERDR-TASK-LIFECYCLE.md` with exact-session recovery,
fallback, cleanup, and operator-visible stale conflict behavior.
