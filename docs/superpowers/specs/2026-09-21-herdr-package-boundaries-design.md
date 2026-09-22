# Herdr package responsibility boundaries

Status: proposed design for the existing Issue #9 / PR #51 branch; not yet
implemented. This follows the agreed coordinator/Issue-worker operating model
in `docs/HERDR-TASK-LIFECYCLE.md`.

## Intent and scope

Make the code structure explain the operational model: Agent management is a
lower-level capability used both by persistent coordinator bootstrap and by
the Issue task lifecycle. The user requested a comprehensible structure and
questioned placing an independent Agent command inside the lifecycle package.
The choice below is a recommendation, not a previously approved package layout.

Keep command behavior and task-state schema stable. Do not implement automatic
coordinator dispatch, reviewer orchestration, session restoration, or a shared
worker pool as part of this refactor.

## Alternatives and decision

1. Keep one distribution, rename it to a broad Herdr automation package, and
   separate task/bootstrap subpackages. This minimizes packaging changes but
   keeps the independent bootstrap application coupled to task dependencies.
2. Put all Agent management and Herdr transport in `herdr_agents`, with
   lifecycle depending on it. This gives Agent operations the right dependency
   direction, but makes task Workspace/Tab operations depend on an Agent-named
   package.
3. Extract a small shared Herdr runtime and make `herdr_agents` the generic
   Agent-management layer above it. Recommended: lifecycle uses runtime for
   Workspace/Tab operations and herdr_agents for Agent operations. Persistent
   coordinator reconciliation is one consumer of the Agent layer, not the
   definition of that layer.

## Layout and dependencies

```text
tools/herdr_runtime/          Python package: herdr_runtime (no CLI)
  client.py                  Herdr CLI adapter and resource information types
  runner.py                  subprocess boundary and command result types
  errors.py                  Herdr/command execution failures

tools/herdr_agents/           Python package: herdr_agents
  service.py                 ensure/prompt an exact named Agent on a Pane
  persistent/
    cli.py                   herdr-agents reconcile entrypoint
    config.py                persistent coordinator TOML definitions
    resolver.py              configured Workspace/cwd -> available Pane
    reconciler.py            reconcile persistent Agent definitions

tools/herdr_task_lifecycle/   Python package: herdr_task_lifecycle
  commands/start/implementer.py
                             Issue naming/prompt/state policy over herdr_agents
  commands/start/service.py  resources -> task state -> implementer
  commands/cleanup/...       task-only cleanup
```

`herdr_agents -> herdr_runtime`.
`herdr_task_lifecycle -> herdr_agents + herdr_runtime + herdr_task_state`.
The runtime does not import either higher-level package or task state.
herdr_agents does not import lifecycle or task state. The Issue implementer
uses the generic exact-name Agent service but does not read agents.toml. The
persistent reconciler uses the same service for each configured coordinator.
Thus `herdr-agents` is both the natural package for the lower Agent capability
and the command namespace for its persistent reconciliation operation.

The generic service owns behavior common to both paths: list by exact managed
name, start on an explicit Pane, validate name/Pane/Workspace/cwd, and prompt a
named Agent. It does not know Issue numbers, task state, roles, TOML, or initial
Issue-prompt contents. The persistent subpackage owns TOML and independent
multi-Agent reconciliation. Lifecycle owns deterministic task names, the
implementer role, initial Issue instructions, and persistence in task state.

Move the existing adapter's task-specific Workspace/Tab operation Protocols
into lifecycle. In the runtime, keep generic resource dataclasses and expose
focused clients through `HerdrClient.workspace`, `.tab`, `.pane`, and `.agent`;
the facade itself only composes those clients over a shared JSON transport.
Agent lookup belongs to the Agent client rather than the `AgentInfo` value or
the policy-level `AgentManager`. Agent operation Protocols and the generic
service belong to herdr_agents. Use concrete JSON boundary types (Any/cast only
at decoding boundaries) instead of spreading object-valued mappings into
application APIs.

## Commands, packaging and errors

Keep the public names `herdr-task` and `herdr-agents`; avoid introducing a
singular alias during this change. Move the latter script registration out of
the lifecycle pyproject into herdr_agents, pointing at `persistent.cli`. Add a
thin `bin/herdr-agents` wrapper and update the systemd bootstrap wrapper to use
that project/entrypoint.
Retain server readiness, flock, environment overrides and missing-config
behavior. The runtime exposes no user command.

Each new project has its own pyproject.toml and uv.lock, uses the pinned
mise-managed Python and uv, and needs no new third-party runtime dependency.
Declare local project dependencies explicitly and verify transitive resolution
from each application's own environment. Keep runtime/development dependencies
scoped to their projects, including pytest/Ruff where tests reside.

Runtime failures use a runtime-owned exception; application failures use their
own exception types. Application CLI boundaries convert both to the existing
exit/output contract. Internal recovery/rollback handlers must still catch the
runtime failures they previously caught as LifecycleError; changing imports
must not change cleanup retry or partial-start behavior. Preserve concise
errors without exposing raw subprocess output.

## Migration and verification

Rename commands/start/agent.py to implementer.py and reduce it to Issue policy
over the generic Agent service. Update its consumers. Move the old agents
subpackage into the new herdr_agents project, separating generic service tests
from persistent reconciliation tests. These are internal Python paths, so no
forwarding compatibility modules are planned. External command names, flags,
state files and configuration paths remain compatible.

Move adapter tests to runtime and generic Agent plus config/reconciliation
tests to herdr_agents; keep Issue policy and cleanup behavior tests in
lifecycle. Verify existing behavior,
failure isolation, retry and rollback handling, and isolated installation of
both CLI projects. Run pytest and Ruff for affected projects, shell bootstrap
and documentation checks, and command help smoke tests without starting live
Agents. Check that herdr_agents can import/run without lifecycle/task-state
installed, and that lifecycle invokes the generic Agent service with the
focused runtime Agent client. Update operator docs with the actual final module
map.

The existing lifecycle documentation test rejects any local agents.toml file;
adjust that check to verify Git exclusion rather than file absence, because a
valid user configuration must not make the test fail.

Use the existing feature branch/PR. Preserve the task workspace for review,
commit intended changes with Generated-by: Codex, push, and keep human review
as the merge gate. Existing untracked .superpowers working notes stay out of
commits.
