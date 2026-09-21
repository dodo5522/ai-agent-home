# Herdr package responsibility boundaries

Status: proposed design for the existing Issue #9 / PR #51 branch; not yet
implemented. This follows the agreed coordinator/Issue-worker operating model
in `docs/HERDR-TASK-LIFECYCLE.md`.

## Intent and scope

Make the code structure explain the operational model: persistent coordinator
bootstrap and Issue task lifecycle are separate applications. Both use typed
Herdr operations. The user requested a comprehensible structure and questioned
placing an independent Agent command inside the lifecycle package. The choice
below is a recommendation, not a previously approved package layout.

Keep command behavior and task-state schema stable. Do not implement automatic
coordinator dispatch, reviewer orchestration, session restoration, or a shared
worker pool as part of this refactor.

## Alternatives and decision

1. Keep one distribution, rename it to a broad Herdr automation package, and
   separate task/bootstrap subpackages. This minimizes packaging changes but
   keeps the independent bootstrap application coupled to task dependencies.
2. Put all Agent/bootstrap code and Herdr transport in `herdr_agents`, with
   lifecycle depending on it. This uses fewer packages, but task cleanup and
   workspace operations would depend on a coordinator-bootstrap package.
3. Give each application its own package and extract a small shared Herdr
   runtime. Recommended: the dependency direction and installation boundaries
   directly match the responsibilities, at the cost of two additional projects.

## Layout and dependencies

```text
tools/herdr_runtime/          Python package: herdr_runtime (no CLI)
  client.py                  Herdr CLI adapter and resource information types
  runner.py                  subprocess boundary and command result types
  errors.py                  Herdr/command execution failures

tools/herdr_agents/           Python package: herdr_agents
  cli.py                     herdr-agents reconcile entrypoint
  config.py                  persistent coordinator TOML definitions
  resolver.py                configured Workspace/cwd -> available Pane
  reconciler.py              start missing named persistent Agents

tools/herdr_task_lifecycle/   Python package: herdr_task_lifecycle
  commands/start/implementer.py
                             Issue-specific naming, identity checks, prompt
  commands/start/service.py  resources -> task state -> implementer
  commands/cleanup/...       task-only cleanup
```

`herdr_agents -> herdr_runtime`.
`herdr_task_lifecycle -> herdr_runtime + herdr_task_state`.
The runtime does not import either application or task state. The bootstrap
application does not import lifecycle or task state. The Issue implementer
does not read agents.toml. A generic Agent service is not introduced solely to
hide existing HerdrClient calls: shared start/list/prompt operations already
belong to the runtime; application-specific policies remain separate.

Move the existing adapter's task-specific operation Protocols into lifecycle;
keep generic resource dataclasses and CLI serialization in the runtime. Use
concrete JSON boundary types (Any/cast only at decoding boundaries) instead of
spreading object-valued mappings into application APIs.

## Commands, packaging and errors

Keep the public names `herdr-task` and `herdr-agents`; avoid introducing a
singular alias during this change. Move the latter script registration out of
the lifecycle pyproject into herdr_agents. Add a thin `bin/herdr-agents` wrapper
and update the systemd bootstrap wrapper to use that project/entrypoint.
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

Rename commands/start/agent.py to implementer.py and update its consumers so
the filename communicates its task-specific responsibility. Remove the old
agents subpackage after moving tests and imports. These are internal Python
paths, so no forwarding compatibility modules are planned. External command
names, flags, state files and configuration paths remain compatible.

Move adapter tests to runtime and config/reconciliation tests to herdr_agents;
keep Issue and cleanup behavior tests in lifecycle. Verify existing behavior,
failure isolation, retry and rollback handling, and isolated installation of
both CLI projects. Run pytest and Ruff for affected projects, shell bootstrap
and documentation checks, and command help smoke tests without starting live
Agents. Check that herdr_agents can import/run without lifecycle/task-state
installed. Update operator docs with the actual final module map.

The existing lifecycle documentation test rejects any local agents.toml file;
adjust that check to verify Git exclusion rather than file absence, because a
valid user configuration must not make the test fail.

Use the existing feature branch/PR. Preserve the task workspace for review,
commit intended changes with Generated-by: Codex, push, and keep human review
as the merge gate. Existing untracked .superpowers working notes stay out of
commits.
