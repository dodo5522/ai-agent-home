# Issue #9 Agent Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reconcile multiple Herdr-backed Codex Agents independently by exact managed Agent name and start the Issue implementer in the state-recorded Issue Pane.

**Architecture:** Add a focused Agent-management module to the existing Python lifecycle package. A TOML loader produces validated immutable Agent definitions; a Herdr adapter exposes typed Agent and Pane operations; an idempotent reconciler compares exact names and starts only missing Agents. The existing shell bootstrap remains responsible only for server readiness/locking and delegates reconciliation, while `herdr-task start` calls the same service for the task-scoped implementer.

**Tech Stack:** Python 3.14.7, `tomllib`, existing `herdr-task` package, Herdr JSON CLI, pytest 8.4.2, Ruff 0.14.10, Bash wrapper.

**Spec:** `docs/superpowers/specs/2026-09-21-issue-9-agent-management-design.md`

## Global Constraints

- Agent names are the stable ownership key; match exact names and never use bare `agent == "codex"` as ownership.
- Model selection and task-complexity routing are out of scope for #9 and belong to #44.
- Codex session discovery/resume and `codex_session_id` handling are out of scope for #9 and belong to #10.
- Background resource creation uses `--no-focus`; Agent startup uses an explicit Pane ID because the installed `herdr agent start` command has no `--no-focus` option. No operation relies on focused panes, terminal IDs, list order, or fixed opaque IDs.
- Shell remains limited to server readiness, locking, environment setup, and delegation to Python.
- Use the mise-managed Python/uv project and standard-library modules where sufficient; do not add runtime dependencies.
- Every commit uses a concise conventional subject, a blank line, and the `Generated-by: Codex` trailer.

## Review Focus

- A malformed or missing TOML file must fail safely before any Herdr mutation; a missing optional config means no bootstrap definitions.
- Two Agent definitions targeting one workspace must not accidentally select the same busy Pane or duplicate a live Agent.
- A live Agent with the same name but a different Pane/cwd must not be restarted or silently adopted as the task Agent.
- A failed start must not abort independent reconciliation or restart already-live Agents.
- A task-start prompt must be sent only to the exact state-recorded Issue Agent and must not target the focused Pane.

---

### Task 1: Add validated Agent configuration loading

**Files:**
- Create: `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/agents/config.py`
- Create: `tools/herdr_task_lifecycle/tests/agents/test_config.py`
- Modify: `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/agents/__init__.py`

**Interfaces:**
- Produces `AgentDefinition(name: str, role: str, workspace: str, cwd: Path)` as a frozen dataclass.
- Produces `load_agent_definitions(path: Path) -> tuple[AgentDefinition, ...]`.
- Consumes TOML shaped as `[agents.<name>]` with exactly `role`, `workspace`, and `cwd` fields.

- [ ] **Step 1: Write failing tests** for a valid two-Agent TOML document, missing-file behavior, unknown fields, invalid names, empty values, relative cwd, and duplicate definitions.
- [ ] **Step 2: Run the focused tests** with `uv run --project tools/herdr_task_lifecycle pytest tools/herdr_task_lifecycle/tests/agents/test_config.py -q`; confirm failure because the loader does not exist.
- [ ] **Step 3: Implement the frozen definition and `tomllib` loader**. Validate the top-level `agents` table, exact fields, lower-case slug names, non-empty strings, absolute directories, and deterministic name ordering. Raise `LifecycleError` with concise path/name context and make an absent file return an empty tuple.
- [ ] **Step 4: Re-run the focused tests**, then run `uv run --project tools/herdr_task_lifecycle ruff check tools/herdr_task_lifecycle/src/herdr_task_lifecycle/agents tools/herdr_task_lifecycle/tests/agents`.
- [ ] **Step 5: Commit** with `feat: add TOML Agent configuration loader` and the required trailer.

### Task 2: Extend the typed Herdr boundary for Agent reconciliation

**Files:**
- Modify: `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/herdr.py`
- Modify: `tools/herdr_task_lifecycle/tests/commands/start/test_service.py`
- Create: `tools/herdr_task_lifecycle/tests/agents/test_reconciler.py`

**Interfaces:**
- Produces `AgentInfo(name: str, kind: str, pane_id: str, workspace_id: str, cwd: Path)` and `PaneInfo` identity/cwd data needed for target selection.
- Extends `_HerdrOperations` with `agents() -> list[AgentInfo]`, `pane_get(pane_id: str) -> PaneInfo`, `panes(workspace_id: str) -> list[PaneInfo]`, `agent_start(name: str, pane_id: str, kind: str = "codex") -> AgentInfo`, and `agent_prompt(name: str, text: str) -> None`.
- Consumes Herdr JSON responses and validates returned names, IDs, workspace relationships, and cwd values before returning typed data.

- [ ] **Step 1: Write failing adapter tests** for valid Agent list parsing, malformed/mismatched Agent identity, pane cwd parsing, `agent start --kind codex --pane ...` argument construction, and exact prompt targeting.
- [ ] **Step 2: Run the focused adapter tests** and confirm they fail because the typed methods are absent.
- [ ] **Step 3: Implement the typed Herdr operations** using the existing `_request` boundary. Preserve current workspace/tab behavior and keep agent operations free of global focus assumptions. Build Agent startup as `herdr agent start <name> --kind codex --pane <pane-id>`; do not invent a `--no-focus` flag because the installed CLI does not support it. Explicit Pane targeting is the safety boundary.
- [ ] **Step 4: Re-run adapter tests and the existing lifecycle start tests**; run Ruff on modified Python files.
- [ ] **Step 5: Commit** with `feat: add typed Herdr Agent operations` and the required trailer.

### Task 3: Implement idempotent per-Agent reconciliation

**Files:**
- Create: `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/agents/reconciler.py`
- Create: `tools/herdr_task_lifecycle/tests/agents/test_reconciler.py`
- Modify: `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/errors.py`

**Interfaces:**
- Produces `AgentReconcileResult(started: tuple[str, ...], skipped: tuple[str, ...], failed: tuple[tuple[str, str], ...])`.
- Produces `AgentReconciler(herdr, pane_resolver).reconcile(definitions) -> AgentReconcileResult`.
- `pane_resolver(definition: AgentDefinition) -> str` returns a validated available Pane for that definition without using focus or list position.

- [ ] **Step 1: Write failing tests** for two missing Agents starting independently, a second run skipping both live Agents, one missing Agent restarting alone, one failed start not affecting another, and an exact-name mismatch not counting as a live Agent.
- [ ] **Step 2: Run the focused tests** and confirm the expected missing-reconciler failures.
- [ ] **Step 3: Implement reconciliation**. Snapshot the live Agent list once, index by exact name, resolve/start only absent definitions, collect per-name failures, and raise/return a result that preserves successful independent starts. Never terminate, rename, or restart a live Agent.
- [ ] **Step 4: Re-run focused tests and the full lifecycle package tests** with `uv run --project tools/herdr_task_lifecycle pytest -q`; run Ruff on the package.
- [ ] **Step 5: Commit** with `feat: reconcile Herdr Agents by name` and the required trailer.

### Task 4: Replace the global bootstrap behavior with configured reconciliation

**Files:**
- Create: `.config/herdr/agents.toml`
- Create: `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/agents/cli.py`
- Modify: `tools/herdr_task_lifecycle/pyproject.toml`
- Modify: `bin/start-herdr-agents.sh`
- Modify: `tests/install_test.sh`
- Create: `tools/herdr_task_lifecycle/tests/agents/test_cli.py`

**Interfaces:**
- Adds project entry point `herdr-agents = "herdr_task_lifecycle.agents.cli:main"`.
- `herdr-agents reconcile [--config PATH]` loads definitions and reconciles each independently.
- Shell passes `HERDR_AGENT_CONFIG`, `HERDR_BIN`, and server-ready environment to the Python entry point; it no longer exits solely because any Codex Agent exists.

- [ ] **Step 1: Write failing CLI and shell-contract tests** for two configured starts, idempotent rerun, missing config, per-Agent failure exit status, and absence of the old global `select(.agent == "codex")` guard.
- [ ] **Step 2: Run the tests** and confirm they fail because the entry point and new delegation are absent.
- [ ] **Step 3: Implement the CLI and thin wrapper**. Keep the existing server wait and `flock`; let Python validate/reconcile definitions and print concise per-Agent results without tokens or raw Herdr output. Set the default config to the repository’s `.config/herdr/agents.toml` and make an empty default file safe.
- [ ] **Step 4: Re-run the focused tests, `tests/install_test.sh`, and the full Python suites for both lifecycle and state packages.
- [ ] **Step 5: Commit** with `feat: reconcile configured Herdr Agents` and the required trailer.

### Task 5: Connect Issue task startup to its implementer Agent

**Files:**
- Modify: `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/commands/start/service.py`
- Modify: `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/commands/start/command.py`
- Modify: `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/herdr.py`
- Modify: `tools/herdr_task_lifecycle/tests/commands/start/test_service.py`

**Interfaces:**
- Produces `TaskStarter(..., agent_starter: TaskAgentStarter | None = None)` while preserving dependency injection for existing tests.
- `TaskAgentStarter.ensure_implementer(task_key: TaskKey, task: Task, pane_id: str) -> AgentReference` starts the deterministic task Agent if absent and prompts it with the Issue number/title/worktree context.
- The stored Agent reference uses the existing `workstreams.main.agents` map and does not set `codex_session_id`.

- [ ] **Step 1: Write failing tests** proving a new Issue start calls Agent start on the returned root Pane, sends one initial prompt to that exact Agent, stores the Agent name, re-running does not duplicate it, and a failed Agent start leaves the managed Workspace/Tab/state resources intact for retry.
- [ ] **Step 2: Run the focused start tests** and confirm they fail because task startup currently stops after Pane/state reconciliation.
- [ ] **Step 3: Implement the task Agent service and call it after successful task resource persistence**. Validate the Agent identity returned for the requested Pane before storing the reference. Preserve existing rollback rules and surface an Agent-specific lifecycle error without closing state-owned resources.
- [ ] **Step 4: Re-run all start-command tests and the full lifecycle/state suites; run Ruff.
- [ ] **Step 5: Commit** with `feat: start an implementer Agent for Issue tasks` and the required trailer.

### Task 6: Document operations and perform whole-branch verification

**Files:**
- Modify: `docs/HERDR-TASK-LIFECYCLE.md`
- Modify: `docs/HERDR-SYSTEMD-SETUP.md`
- Modify: `README.md`
- Modify: `tests/herdr_task_lifecycle_test.sh`
- Modify: `tests/install_test.sh`

**Interfaces:**
- Documents `.config/herdr/agents.toml`, `herdr-agents reconcile`, exact-name ownership, task implementer startup, #10 session boundary, and #44 model-routing boundary.

- [ ] **Step 1: Write failing documentation-contract assertions** for the config path, exact Agent name rule, per-Agent recovery, task-start Agent startup, and explicit model-routing deferral.
- [ ] **Step 2: Run the documentation tests** and confirm missing-contract failures.
- [ ] **Step 3: Update operator documentation and examples** without promising automatic model selection or session resume in #9.
- [ ] **Step 4: Run the complete verification set:**
  `uv run --project tools/herdr_task_state pytest -q`,
  `uv run --project tools/herdr_task_lifecycle pytest -q`,
  `uv run --project tools/herdr_task_state ruff check .`,
  `uv run --project tools/herdr_task_lifecycle ruff check .`,
  `bash tests/herdr_task_state_test.sh`,
  `bash tests/herdr_task_lifecycle_test.sh`, and
  `bash tests/install_test.sh`.
- [ ] **Step 5: Commit** with `docs: document independent Herdr Agent operations` and the required trailer.
- [ ] **Step 6: Push the feature branch and create a Pull Request targeting `main`, requesting review from `dodo5522`; do not merge it.
