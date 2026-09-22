# Issue #10 Codex Session Mapping Design

## Goal

Resume every managed Herdr Codex Agent into its own recorded Codex session
after an Agent or host restart. A mapping must bind the session to the Agent's
repository, Herdr Workspace, Git worktree, and branch so reconciliation cannot
resume a session that belongs to another project or task.

## Scope

This change implements:

- a private, atomic session-mapping store shared by persistent and task-scoped
  Agents;
- discovery of the exact Codex session ID reported by Herdr;
- explicit `codex resume SESSION_ID` startup for a valid stored mapping;
- fresh-session startup and mapping replacement when no usable session exists;
- binding validation and stale-mapping handling;
- synchronization of Issue Agent session IDs into existing task state; and
- restart tests with multiple Agents, repositories, Workspaces, worktrees, and
  branches.

This change does not make Herdr continuously supervise Agents, create
worktrees, dispatch coordinator requests, add reviewer Panes, or select models.
It also does not infer a session from recency. In particular, automation must
not use `codex resume --last --all`.

## Ownership and package boundaries

`herdr_runtime` decodes the optional Codex session identity exposed by Herdr
and passes explicit native arguments to `herdr agent start`.

`herdr_agents` owns session binding, persistence, validation, and the generic
start-or-resume decision. The existing exact-name `AgentManager` remains the
single entry point used by persistent reconciliation and Issue lifecycle.

`herdr_task_lifecycle` supplies repository and branch identity from its
validated task/worktree state. After an Issue Agent is successfully reconciled,
it mirrors the observed session ID into
`workstreams.<workstream>.agents.<role>.codex_session_id` atomically with the
Agent reference. Task state remains the operator-visible task record; the
shared session store is the generic recovery source for all managed Agents,
including persistent coordinators that have no Issue task.

The shared mapping is committed first and the task-state mirror second; the two
files cannot form one filesystem transaction. If the second write fails, the
next reconciliation uses a validated live observation to repair the mirror.
Without a matching live observation, differing IDs remain a reported conflict.

The dependency direction remains:

```text
herdr_task_lifecycle -> herdr_agents -> herdr_runtime
                     -> herdr_task_state
```

## Session mapping store

The default mapping path is
`${XDG_STATE_HOME:-$HOME/.local/state}/ai-agent-home/herdr-agent-sessions.json`.
Tests may override it with `HERDR_AGENT_SESSION_FILE`. The adjacent lock file,
directory permissions, file permissions, strict JSON parsing, atomic replace,
and failure cleanup follow the existing task-state store conventions.

The version 1 document contains a map keyed by exact managed Agent name. Each
record contains:

- `codex_session_id`: the non-empty ID reported by Herdr;
- `repository`: normalized lower-case `owner/name`;
- `workspace_id`: the opaque live Herdr Workspace ID;
- `workspace_label`: the expected repository Workspace label;
- `worktree`: resolved absolute Git worktree path;
- `branch`: attached local branch name; and
- `pane_id`: the last validated Pane ID, retained as diagnostic placement data.

Agent name is the stable lookup key. Pane and Workspace IDs are runtime
references and never establish ownership on their own. A Codex session ID may
appear in only one Agent record. Unknown fields are accepted for forward
compatibility, while changing an existing field's meaning requires a schema
version migration. The store contains identifiers and paths only; credentials,
prompts, transcripts, and token material are prohibited.

The store exposes lock-scoped read, compare, put, and remove operations. A
reconciler computes its decision from one locked current record and commits the
new observation without overwriting unrelated Agent records. Concurrent
reconciliation therefore cannot lose another Agent's mapping or assign one
session to two Agents.

## Binding identity

Every reconciliation call supplies an `AgentTarget` with the exact Agent name,
Pane ID, Workspace ID and label, repository, resolved worktree path, and
attached branch. Persistent Agent definitions continue to contain a Workspace
label and cwd; the resolver derives repository identity from the normalized
Git `origin` and derives the attached branch from Git. A definition whose cwd
is not the root of an attached worktree, has no branch, or resolves to a
different repository than its Workspace label fails before Agent startup.

Issue lifecycle supplies these fields from its already validated origin, task
state, and worktree registration. Thus both callers reach the same generic
session policy without `herdr_agents` depending on task state.

The stored binding must exactly match repository, Workspace ID and label,
resolved worktree, and branch before its session ID can be resumed. Pane ID is
not part of stable ownership: a task may recreate a recorded Pane while keeping
the same worktree and session. The mapping records the new Pane after a
successful reconciliation.

## Reconciliation flow

For each exact managed Agent name:

1. Resolve and validate the complete target binding.
2. Find the exact live Agent.
3. If it is live, validate its Pane, Workspace, cwd, kind, and reported Codex
   session ID. Record that observed session against the target binding. A live
   Agent is authoritative only after all placement checks pass.
4. If it is absent and no mapping exists, start a fresh Codex Agent on the
   exact Pane, read its reported session ID, and persist the new mapping.
5. If it is absent and a mapping exactly matches the target binding, start the
   Agent with native arguments `resume SESSION_ID`, validate that Herdr reports
   the same session ID, and refresh the Pane field.
6. If explicit resume proves that the session is absent or unreadable, remove
   only that exact stale record, wait until the target Pane is again an
   available shell, start a fresh Codex Agent, and persist its new session ID.
7. Return the reconciled Agent and whether it was reused, resumed, or freshly
   started. Issue lifecycle uses the returned session ID when updating task
   state.

Herdr startup results must distinguish a blocked or still-running Agent from a
process that exited because the requested session could not be loaded. The
fallback applies only to the latter condition. Authentication failures,
approval prompts, timeouts with a live process, unavailable Panes, and unknown
startup errors remain failures and never trigger a second Agent in the Pane.

The initial Issue prompt is sent only for a freshly created session. A resumed
session already contains its task context and must not receive the original
"Begin implementation" prompt again.

## Stale and conflicting mappings

Stale state is handled according to evidence:

- A missing mapping starts fresh and records the observed session.
- An exact binding whose session is conclusively absent or unreadable is
  replaced through the fallback flow.
- A binding mismatch is a conflict. Reconciliation reports the mismatched
  fields and does not resume, delete, or replace that record automatically.
- A session ID already owned by another Agent record is a conflict, even when
  the other record appears old.
- A live exact-name Agent with a valid target placement but a different
  reported session updates its own mapping only when that session is not owned
  elsewhere. This covers an operator-started replacement without selecting it
  by recency.
- A live Agent without a reported Codex session ID is not considered safely
  reconciled and is not written to either store.
- If Issue task state and the shared mapping contain different session IDs for
  the same Agent and binding, task reconciliation reports a conflict. It does
  not silently choose one. A successful live observation can repair both only
  when the observed ID is unclaimed and all target fields validate.

Diagnostics may include Agent names, resource IDs, paths, branches, and session
IDs, but never raw subprocess output that could contain credentials.

## Bootstrap and failure isolation

The existing bootstrap order remains: wait for the Herdr server, then run
`herdr-agents reconcile`. Each persistent definition is resolved and reconciled
independently. One stale, conflicting, or failed Agent is reported in the
result and does not prevent later definitions from being restored.

Issue `herdr-task start` continues to persist Workspace, Tab, Pane, worktree,
and branch before Agent reconciliation. A session failure leaves those managed
resources and the previous mapping available for inspection and retry. It does
not roll back or close another resource.

## Testing

Unit tests use fake Herdr and filesystem boundaries to prove:

- strict mapping validation, private permissions, atomic writes, locking, and
  preservation of unrelated mappings;
- Herdr decoding of present, absent, and malformed `agent_session` data;
- fresh start arguments contain no recency-based resume option;
- exact resume uses `resume SESSION_ID` on the requested Pane;
- a valid live Agent records its actual session and never starts a duplicate;
- a binding mismatch, duplicate session owner, or task/shared-state mismatch
  fails without mutation;
- a conclusively missing or corrupt session falls back once to fresh startup,
  while blocked and ambiguous failures do not;
- resumed Issue Agents do not receive a duplicate initial prompt;
- task state records the successfully observed session ID; and
- failure of one persistent Agent does not prevent another from restoring.

An isolated reboot-style integration test will create at least two managed
Codex Agents in different repository/worktree bindings, capture their distinct
session IDs, restart the test Herdr session/bootstrap, and verify that each
Agent returns on its recorded Pane with the same ID. A negative case swaps or
changes one binding and verifies that no session is resumed into the wrong
project. The test must use a named isolated Herdr session and temporary state;
it must not stop or mutate the operator's active Herdr session.

Before publication, run Ruff and pytest for `herdr_runtime`, `herdr_agents`,
`herdr_task_state`, and `herdr_task_lifecycle`, followed by the isolated
restart test when the installed Herdr/Codex environment supports it.

## Documentation updates

Update `docs/HERDR-TASK-STATE.md` with the mirrored session field and conflict
rule. Update `docs/HERDR-TASK-LIFECYCLE.md` so the capability table and startup
sequence describe exact-session recovery and its fallback. Document the shared
mapping path, binding fields, and operator-visible stale conflict behavior.

Successful Issue cleanup retires the exact task Agent mapping after its Tab,
worktree, and task root are gone and immediately before removing task state.
Retirement removes only the association; it does not delete Codex session
files. It validates the Agent name and stored task binding, is idempotent for an
already absent record, and preserves the task mapping if it fails so cleanup
can be retried. Cleanup planning displays this mapping action, and cleanup
progress records it as a distinct completed action. Persistent coordinator
mappings remain outside Issue cleanup ownership.
