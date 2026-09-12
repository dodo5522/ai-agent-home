# Herdr Task Lifecycle Design

## Goal

Replace the newly introduced standalone Issue-start command with one canonical
`herdr-task` CLI. In this Issue it provides safe `start` and `cleanup`
subcommands, keeps managed Herdr and Git resources traceable by Issue task
identity, and establishes a single operational reference for their lifecycle.

## Scope

This change implements:

- `herdr-task start ISSUE [--cwd PATH]`, which preserves the existing
  task-start reconciliation behavior.
- `herdr-task cleanup ISSUE --plan` and `herdr-task cleanup ISSUE --execute`,
  including live-resource validation, resumable partial cleanup, and task-root
  safety boundaries.
- the state fields needed to record cleanup progress without losing the task
  mapping before cleanup has completed.
- `docs/HERDR-TASK-LIFECYCLE.md` as the sole operational specification, with
  brief links from README, AGENTS, and task-state documentation.
- integration tests using a fake Herdr client and isolated Git worktrees.

This change does not implement PR metadata commands or Pane-add commands.
Those operations will be tracked in new follow-up Issues. The lifecycle
document will reserve their role names and creation rules without defining a
second detailed specification.

## CLI boundary

`herdr-task` is the canonical command and exposes action-oriented subcommands:

```text
herdr-task start ISSUE [--cwd PATH]
herdr-task cleanup ISSUE --plan
herdr-task cleanup ISSUE --execute --confirm-task-root PATH
```

`--plan` is read-only and emits one JSON cleanup plan. `--execute` requires
the exact absolute task-root path returned by the plan. An agent must show the
plan and receive human approval before invoking `--execute`; the option makes
that approval deliberate and prevents a copied command from deleting a
different task root.

The old `herdr-task-start` wrapper and `tools/herdr_task_start` package are
removed. They were only used during initial testing, so no compatibility alias
is retained.

Future operations belong under the same executable, for example
`herdr-task pr ...` and `herdr-task pane ...`; they are not accepted command
names in this release.

## Package structure

The lifecycle package keeps cross-cutting code at the package root and makes
each command own its implementation directory:

```text
tools/herdr_task_lifecycle/
├── pyproject.toml
├── uv.lock
├── src/herdr_task_lifecycle/
│   ├── __init__.py
│   ├── cli.py                 # root parser and command registration
│   ├── errors.py              # stable errors and exit codes
│   ├── runner.py              # subprocess boundary
│   ├── state.py               # state-store adapter and shared mutations
│   ├── herdr.py               # Herdr JSON API adapter
│   ├── identity.py            # Git remote and GitHub Issue lookup
│   └── commands/
│       ├── __init__.py
│       ├── start/
│       │   ├── __init__.py
│       │   ├── command.py     # start CLI wiring
│       │   └── service.py     # workspace / tab reconciliation
│       └── cleanup/
│           ├── __init__.py
│           ├── command.py     # cleanup CLI wiring
│           ├── planner.py     # validation and deterministic plan creation
│           └── executor.py    # ordered, resumable plan execution
└── tests/
    ├── commands/
    │   ├── start/
    │   └── cleanup/
    └── test_cli.py
```

The package depends on the existing `herdr-task-state` package. It uses the
mise-managed Python version, `uv`, pytest, Ruff, and standard-library
filesystem and Git process handling; no new runtime dependency is needed.

`bin/herdr-task` is a thin Bash wrapper that starts the package with the
repository's mise-managed `uv`. It contains no task lifecycle logic.

## Start behavior

The `start` service is migrated from `herdr_task_start` without changing its
observable safety contract:

- require `HERDR_ENV=1`;
- resolve repository identity from the current Git `origin` and Issue title
  from GitHub CLI JSON;
- create or reuse only state-recorded managed workspace and Tab IDs;
- use repository label for the workspace and `<issue> <short title>` for the
  Tab;
- create resources with `--no-focus` and validate a single root Pane;
- save the resolved IDs atomically; and
- roll back only resources created by the failed invocation.

The GitHub CLI invocation must use the configured GitHub App token when
available, without requiring an interactive `gh auth login`. It must never
echo token material or raw command output in an error.

## Cleanup model and safety boundaries

Cleanup starts from the stable task key and only considers resources referenced
by that task's state record. It never discovers cleanup targets by labels.

The plan validates each stored reference against live state and reports one of
three outcomes per action:

| Outcome | Meaning | Execute behavior |
| --- | --- | --- |
| `delete` | The managed reference still matches its live identity. | Perform the action. |
| `already_absent` | The stored resource no longer exists. | Record no destructive action; continue. |
| `blocked` | The resource is mismatched, unsafe, or cannot be validated. | Do not execute any action. |

The executor runs actions in this order:

1. close each validated managed Issue Tab, never the repository workspace;
2. remove each validated registered Issue worktree through Git;
3. recursively remove the one validated task root; and
4. remove the task mapping from state only after every prior action has
   completed or was already absent.

Tab validation requires stored Tab ID, workspace ID, and expected label to
match live Herdr data. The executor does not separately close Panes because
closing the validated managed Tab owns that action.

Worktree removal requires the stored absolute worktree path to be a registered
non-primary worktree for the task repository. The executor never removes a
repository's primary checkout.

Task-root removal is allowed only when all conditions hold:

- the resolved root is strictly below `/home/takashi/work/tasks/`;
- it is neither `/home/takashi/work` nor `/home/takashi/work/tasks`;
- `.codex-task-root` exists directly inside it;
- no Git repository has a registered worktree under it after planned worktree
  removals; and
- `--confirm-task-root` exactly equals the resolved root.

The root is removed as one recursive operation only after the human-approved
plan has passed those checks. Cleanup never deletes the repository workspace,
an unmanaged Herdr resource, or a different task's data.

## Resumability

Task state gains an optional typed `cleanup` record. It contains the resolved
task-root path, a `pending` or `partial` phase, and the set of completed action
identifiers. Before the first destructive action, cleanup progress is written
atomically. Each successful or already-absent action is recorded atomically
before the next action begins.

If execution fails, the mapping and progress remain. A later `--plan`
re-validates live state and produces only remaining work. A later `--execute`
continues from that plan. When all actions are complete, the cleanup record and
the entire task mapping are removed atomically.

## Operational documentation

`docs/HERDR-TASK-LIFECYCLE.md` is the source of truth for:

- stable task and workstream identities;
- workspace, Tab, Pane, Agent, worktree, task-root, and PR metadata roles;
- labels, cwd rules, creation and reuse triggers;
- `start`, PR-open/review retention, merge cleanup, and non-PR completion
  triggers;
- future PR and Pane command boundaries; and
- cleanup review, approval, execution, and retry procedure.

README and AGENTS contain only summaries and links. `HERDR-TASK-STATE.md`
keeps the low-level state schema and CLI reference, then links to this
document for lifecycle behavior. No separate task-start operating document
remains.

## Verification

Tests are written first and cover at least:

- `start` command migration and its existing no-duplicate, stale-state, and
  rollback contracts;
- a cleanup plan that lists only managed resources and is read-only;
- successful cleanup in the defined action order;
- rejection of workspace, Tab, worktree, or task-root identity mismatches;
- prevention of root deletion without exact confirmation or marker/boundary
  checks;
- no cleanup of unmanaged resources or another task's resources; and
- a partial failure whose next execution safely resumes from persisted state.

The relevant pytest suites, Ruff formatting and lint checks, and package
entrypoint smoke tests must pass before a Pull Request is created.
