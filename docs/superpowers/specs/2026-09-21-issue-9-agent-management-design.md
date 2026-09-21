# Issue #9 Agent Management Design

## Goal

Manage multiple Herdr-backed Codex Agents independently by task-scoped Agent
name. Starting or recovering one Agent must not be suppressed by, duplicate, or
restart another Agent.

## Scope

This change implements:

- declarative Agent definitions in a human-editable TOML configuration file;
- Agent discovery by exact managed Agent name rather than bare Agent kind;
- idempotent reconciliation of configured Agents;
- independent startup and recovery of each configured Agent;
- task-start integration for the Issue implementer Agent on the registered root
  Pane; and
- unit and integration tests covering multiple Agents, duplicate prevention,
  isolated recovery, and task Pane targeting.

This change does not implement Codex session discovery or resume behavior. That
remains Issue #10's responsibility. It also does not create Git worktrees or
additional role Panes; those resources must already exist or be supplied by the
caller and the existing task lifecycle.

Model selection and task-complexity-based routing are explicitly out of scope.
Issue #44 owns model/sub-agent routing for Blender work, including per-Agent
model configuration and fallback policy. #9 must not infer that Codex chooses a
model automatically from task complexity.

## Configuration

The managed Agent configuration is stored at `.config/herdr/agents.toml` and is
read with Python's standard-library `tomllib`. The file is human-maintained and
read-only for the reconciler. Each definition has a unique Agent name, role,
workspace label, and absolute cwd:

```toml
[agents.codex-main]
role = "implementer"
workspace = "dodo5522/ai-agent-home"
cwd = "/home/takashi"

[agents.codex-reviewer]
role = "reviewer"
workspace = "dodo5522/ai-agent-home"
cwd = "/home/takashi"
```

Agent names are the stable ownership key. Configuration validation rejects
duplicate or invalid names, unknown fields, relative cwd values, empty values,
and definitions whose workspace/cwd cannot be resolved safely. A missing file
means no configured bootstrap Agents; malformed configuration is a concise
runtime error and must not partially reconcile the list.

Issue implementer Agents use a deterministic task-scoped name and the
state-recorded Issue Workspace/Tab root Pane. They are not inferred from a
global `codex` Agent and are not allowed to take an unrelated focused Pane.

## Reconciliation behavior

The Agent reconciler runs once for each configured definition:

1. Discover live Agents from `herdr agent list`.
2. Match only the exact configured Agent name.
3. If that Agent is live, leave it unchanged regardless of other Agent states.
4. If it is absent, resolve the configured or task-provided Pane by validated
   workspace/cwd identity and start exactly that Agent with `herdr agent start`.
5. Use an explicit Pane ID and never depend on global focus, terminal ID, list
   order, or bare Agent kind. The installed `herdr agent start` command does
   not expose a `--no-focus` option; explicit Pane targeting is the supported
   non-ambiguous boundary for Agent startup.

The operation is idempotent: repeating it with the same live Agent set makes
no additional start calls. If one Agent is absent while others are live, only
the absent Agent is started. A failed start for one definition is reported
with its name and does not cause already-live Agents to be restarted; the
reconciler returns a non-zero result after evaluating the remaining
definitions so independent recovery is preserved.

The existing shell bootstrap becomes a thin launcher for the Python
reconciler. It retains Herdr server readiness and a process lock, while Agent
selection, validation, and per-Agent recovery move into typed Python code.

## Task-start integration

`herdr-task start ISSUE --cwd WORKTREE` already creates or reuses the managed
Workspace, Issue Tab, and root Pane and persists their IDs. After that state is
stored, the task-start workflow invokes the Agent service for the Issue's
implementer role using the returned task key and root Pane ID. It then sends
the initial Issue instruction to that exact Agent. Agent state is persisted
only after the Herdr Agent start identity has been validated.

If Agent startup or prompting fails, the lifecycle command reports the Agent
failure without closing the already state-owned Workspace or Tab. Re-running
the command reconciles the missing Agent without duplicating the task
resources.

## State and Issue #10 boundary

The existing `workstreams.<name>.agents` map remains the source of the
task-to-Agent reference. #9 stores the managed Agent name and role mapping
when task startup succeeds. It does not populate or interpret
`codex_session_id`; session discovery and resume belong to #10. Existing state
without an Agent entry remains valid and is upgraded on a successful
task-scoped start. It also does not add model fields; a future routing layer may
provide Agent arguments at the startup boundary without making model selection
part of Agent lifecycle ownership.

## Testing

Tests will use a fake Herdr runner/client and prove:

- TOML definitions parse and invalid definitions fail before mutation;
- two configured Agents start in separate target Panes;
- rerunning with both Agents live performs no duplicate starts;
- removing one Agent from the live response starts only that Agent;
- failure of one Agent does not restart or alter another;
- task startup targets the state-recorded Issue Pane and sends the initial
  instruction to the task Agent; and
- the shell bootstrap remains a thin, mise-managed launcher.

The full lifecycle, state, installer, and Agent-management test suites must
pass before the branch is published.
