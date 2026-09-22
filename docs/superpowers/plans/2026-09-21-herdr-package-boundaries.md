# Herdr Package Boundaries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate typed Herdr runtime access, reusable Agent management, and Issue task lifecycle while preserving the existing `herdr-task` and `herdr-agents` behavior.

**Architecture:** `herdr_runtime` owns subprocess and Herdr CLI boundaries. `herdr_agents` depends on it and owns exact-name Agent operations plus persistent coordinator reconciliation. `herdr_task_lifecycle` depends on both packages and adds Issue identity, prompts, state, resources, and cleanup policy.

**Tech Stack:** Python 3.14, standard library, uv 0.12.11, pytest 8.4.2, Ruff 0.14.10, Bash wrappers, Herdr JSON CLI.

**Spec:** `docs/superpowers/specs/2026-09-21-herdr-package-boundaries-design.md`

## Global Constraints

- Preserve public command names, arguments, JSON output, task-state schema, configuration path, and systemd readiness/locking behavior.
- Add no third-party runtime dependency; each tool owns its exact pyproject.toml and uv.lock.
- `herdr_agents` must import and run without `herdr_task_lifecycle` or `herdr_task_state` installed.
- `herdr_task_lifecycle` must use `herdr_agents.AgentManager` for Agent discovery/start/validation/prompt, not call HerdrClient Agent methods directly.
- `agents.toml` remains user-maintained and persistent-coordinator-only; Issue Agents remain task-state-owned.
- Do not implement coordinator dispatch, reviewer orchestration, session restoration, or a shared worker pool.
- Preserve existing partial-start, retry, rollback, cleanup, and concise error behavior.
- Use the current `feat/issue-9-agent-management` branch and PR #51; never merge it.

## Review Focus

- A missing Herdr executable must still become a concise CLI runtime error rather than an uncaught traceback; pin this in Task 1 CLI/error tests.
- A live exact-name Agent on the wrong Pane, Workspace, or cwd must be rejected by the shared service; pin all three identities in Task 2.
- A prompt failure after Agent start must remain retryable because task state has no Agent reference yet; pin this in Task 3.
- A malformed persistent config must cause no Agent mutation, while one failed definition must not stop later definitions; pin both in Task 2.
- A local ignored `.config/herdr/agents.toml` must not break repository checks; pin Git exclusion rather than file absence in Task 4.

---

### Task 1: Extract the shared Herdr runtime

**Files:**
- Create: `tools/herdr_runtime/pyproject.toml`
- Create: `tools/herdr_runtime/uv.lock`
- Create: `tools/herdr_runtime/src/herdr_runtime/__init__.py`
- Create: `tools/herdr_runtime/src/herdr_runtime/errors.py`
- Create: `tools/herdr_runtime/src/herdr_runtime/runner.py`
- Create: `tools/herdr_runtime/src/herdr_runtime/client.py`
- Create: `tools/herdr_runtime/tests/test_client.py`
- Create: `tools/herdr_runtime/tests/test_runner.py`
- Modify: `tools/herdr_task_lifecycle/pyproject.toml`
- Modify: lifecycle source/tests importing `herdr.py` or `runner.py`
- Delete: `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/herdr.py`
- Delete: `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/runner.py`

**Interfaces:**
- Produces: `CommandResult`, `CommandRunner`, `SubprocessRunner`, `RuntimeCommandError`, `HerdrError`, `WorkspaceInfo`, `TabInfo`, `PaneInfo`, `AgentInfo`, `CreatedResources`, and `HerdrClient` under `herdr_runtime`.
- Preserves: all current `HerdrClient` method signatures and JSON validation behavior.
- Consumed later by: `herdr_agents` and `herdr_task_lifecycle`.

- [ ] **Step 1: Add failing runtime import and command-error tests**

Create tests that import the public runtime types and verify an unavailable executable is typed:

```python
def test_missing_command_raises_runtime_command_error(tmp_path: Path) -> None:
    runner = SubprocessRunner()
    with pytest.raises(RuntimeCommandError, match="cannot execute"):
        runner.run([str(tmp_path / "missing")])
```

Move the existing Herdr adapter cases from `tests/agents/test_herdr.py` and cleanup planner tests into `tools/herdr_runtime/tests/test_client.py`, retaining identity mismatch, invalid JSON, missing result, list, create, close, rename, Pane, Agent start, and prompt assertions.

- [ ] **Step 2: Run the runtime tests and verify collection fails**

Run: `uv run --project tools/herdr_task_lifecycle pytest tools/herdr_runtime/tests -q`

Expected: FAIL because `herdr_runtime` does not exist.

- [ ] **Step 3: Implement the runtime project and migrate imports**

Define runtime errors with one catchable base:

```python
class HerdrRuntimeError(Exception):
    pass

class RuntimeCommandError(HerdrRuntimeError):
    pass

class HerdrError(HerdrRuntimeError):
    pass
```

Move `CommandRunner`/`SubprocessRunner` to `runner.py`; raise `RuntimeCommandError` for `OSError`. Move resource dataclasses and `HerdrClient` to `client.py`; convert its user-facing failures to `HerdrError`. Export stable public names from `herdr_runtime.__init__`.

Add the local dependency and source:

```toml
dependencies = [
    "herdr-runtime",
    "herdr-task-state",
]

[tool.uv.sources]
herdr-runtime = { path = "../herdr_runtime" }
herdr-task-state = { path = "../herdr_task_state" }
```

Update lifecycle imports. At CLI boundaries catch `HerdrRuntimeError` alongside `LifecycleError`; in rollback/planning locations that intentionally treat missing live Herdr resources as recoverable, catch `HerdrError`. Preserve lifecycle validation as `LifecycleError`.

- [ ] **Step 4: Generate locks and run focused tests**

Run:

```bash
uv lock --project tools/herdr_runtime
uv lock --project tools/herdr_task_lifecycle
uv run --project tools/herdr_runtime pytest tools/herdr_runtime/tests -q
uv run --project tools/herdr_task_lifecycle pytest tools/herdr_task_lifecycle/tests -q
uv run --project tools/herdr_runtime ruff check tools/herdr_runtime/src tools/herdr_runtime/tests
uv run --project tools/herdr_task_lifecycle ruff check tools/herdr_task_lifecycle/src tools/herdr_task_lifecycle/tests
```

Expected: all pass; lifecycle no longer contains `herdr.py` or `runner.py`.

- [ ] **Step 5: Commit**

```bash
git add tools/herdr_runtime tools/herdr_task_lifecycle
git commit -m "refactor: extract shared Herdr runtime" -m "Move typed Herdr CLI and subprocess boundaries into a dependency shared by Agent and task management." -m "Generated-by: Codex"
```

### Task 2: Extract reusable Agent management and persistent reconciliation

**Files:**
- Create: `tools/herdr_agents/pyproject.toml`
- Create: `tools/herdr_agents/uv.lock`
- Create: `tools/herdr_agents/src/herdr_agents/__init__.py`
- Create: `tools/herdr_agents/src/herdr_agents/errors.py`
- Create: `tools/herdr_agents/src/herdr_agents/service.py`
- Create: `tools/herdr_agents/src/herdr_agents/persistent/__init__.py`
- Create: `tools/herdr_agents/src/herdr_agents/persistent/config.py`
- Create: `tools/herdr_agents/src/herdr_agents/persistent/resolver.py`
- Create: `tools/herdr_agents/src/herdr_agents/persistent/reconciler.py`
- Create: `tools/herdr_agents/src/herdr_agents/persistent/cli.py`
- Create: `tools/herdr_agents/tests/test_service.py`
- Create: `tools/herdr_agents/tests/persistent/test_config.py`
- Create: `tools/herdr_agents/tests/persistent/test_resolver.py`
- Create: `tools/herdr_agents/tests/persistent/test_reconciler.py`
- Create: `tools/herdr_agents/tests/persistent/test_cli.py`
- Modify: `tools/herdr_task_lifecycle/pyproject.toml`
- Delete: `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/agents/`
- Delete: `tools/herdr_task_lifecycle/tests/agents/`

**Interfaces:**
- Consumes: `herdr_runtime.AgentInfo`, `HerdrClient`, `HerdrError`, and `CommandRunner`.
- Produces: `AgentTarget(name: str, pane_id: str, workspace_id: str, cwd: Path)`, `EnsuredAgent(agent: AgentInfo, started: bool)`, `AgentManager.ensure(target)`, `AgentManager.prompt(name, text)`, and persistent config/reconcile CLI.
- `AgentManager.ensure` performs exact-name lookup, starts only when absent, and validates all target identity fields in both paths.

- [ ] **Step 1: Add failing shared-service tests**

Write tests around an injected protocol:

```python
target = AgentTarget("codex-issue-9", "w16:p2", "w16", Path("/work/issue-9"))
result = AgentManager(fake_herdr).ensure(target)
assert result.started is True
assert result.agent.name == target.name
```

Cover: absent Agent starts once; exact live Agent is reused; same name on a different Pane fails; matching Pane but wrong Workspace fails; matching Pane/Workspace but wrong cwd fails; start response mismatch fails; prompt delegates to the exact name. Use `AgentManagementError` for policy/identity failures and let `HerdrError` remain typed as a runtime failure.

- [ ] **Step 2: Run the service tests and verify imports fail**

Run: `uv run --project tools/herdr_runtime pytest tools/herdr_agents/tests/test_service.py -q`

Expected: FAIL because `herdr_agents` does not exist.

- [ ] **Step 3: Implement the generic Agent service**

Use this public shape:

```python
@dataclass(frozen=True)
class AgentTarget:
    name: str
    pane_id: str
    workspace_id: str
    cwd: Path

@dataclass(frozen=True)
class EnsuredAgent:
    agent: AgentInfo
    started: bool

class AgentManager:
    def ensure(self, target: AgentTarget) -> EnsuredAgent: ...
    def prompt(self, name: str, text: str) -> None: ...
```

The service snapshots `agents()`, compares the exact name, validates Pane/Workspace/cwd, and calls `agent_start` only when absent. It contains no task-state, TOML, role, Issue, or initial-prompt logic.

- [ ] **Step 4: Move and adapt persistent reconciliation with failing tests first**

Move config tests unchanged except imports. Split Pane resolution from CLI into `resolver.py` and test no Workspace, duplicate Workspace, no Pane, duplicate Pane, and exact matching Pane. Adapt the reconciler to call `AgentManager.ensure(AgentTarget(...))`; keep `started`, `skipped`, and per-definition `failed` output. Verify malformed TOML performs zero Agent calls and a failed first definition still allows the second to start.

The CLI must catch `AgentManagementError`, `HerdrRuntimeError`, and configuration errors, preserve `herdr-agents reconcile --config`, and emit the existing JSON result document.

- [ ] **Step 5: Add project metadata and verify isolation**

Create `herdr-agents` with only `herdr-runtime` as a runtime dependency:

```toml
[project.scripts]
herdr-agents = "herdr_agents.persistent.cli:main"

[tool.uv.sources]
herdr-runtime = { path = "../herdr_runtime" }
```

Run:

```bash
uv lock --project tools/herdr_agents
uv run --project tools/herdr_agents pytest tools/herdr_agents/tests -q
uv run --project tools/herdr_agents ruff check tools/herdr_agents/src tools/herdr_agents/tests
uv run --project tools/herdr_agents python -c "import herdr_agents; import herdr_agents.persistent.cli"
```

Expected: all pass without lifecycle/task-state as declared dependencies.

- [ ] **Step 6: Remove lifecycle Agent CLI registration and commit**

Remove `herdr-agents` from the lifecycle scripts, remove the old subpackage/tests, regenerate lifecycle lock, and ensure `rg 'herdr_task_lifecycle\.agents' tools` returns no matches.

```bash
git add tools/herdr_agents tools/herdr_task_lifecycle
git commit -m "refactor: extract reusable Herdr Agent management" -m "Provide exact-name Agent operations and persistent coordinator reconciliation in an independent package." -m "Generated-by: Codex"
```

### Task 3: Make Issue lifecycle consume the Agent service

**Files:**
- Create: `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/commands/start/implementer.py`
- Modify: `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/commands/start/command.py`
- Modify: `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/commands/start/service.py`
- Modify: `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/cli.py`
- Create: `tools/herdr_task_lifecycle/tests/commands/start/test_implementer.py`
- Modify: `tools/herdr_task_lifecycle/tests/commands/start/test_service.py`
- Delete: `tools/herdr_task_lifecycle/src/herdr_task_lifecycle/commands/start/agent.py`
- Delete: `tools/herdr_task_lifecycle/tests/commands/start/test_agent.py`
- Modify: `tools/herdr_task_lifecycle/pyproject.toml`
- Modify: `tools/herdr_task_lifecycle/uv.lock`

**Interfaces:**
- Consumes: `AgentManager`, `AgentTarget`, `EnsuredAgent`, and `AgentManagementError` from herdr_agents.
- Preserves: `TaskAgentStarter.ensure_implementer(task_key, task, pane_id) -> AgentReference` for `TaskStarter`.
- Lifecycle owns task-scoped name generation, initial prompt content, and the rule that an absent stored reference requires prompt delivery.

- [ ] **Step 1: Rewrite the implementer tests against a fake AgentManager**

Assert the exact target passed to the lower layer:

```python
assert manager.targets == [
    AgentTarget(task_agent_name(key), "w16:p2", "w16", Path("/work/issue-9"))
]
```

Cover: a new Agent receives one prompt; a stored Agent reference causes no duplicate prompt; an existing but unrecorded live Agent receives the retry prompt; prompt failure propagates so TaskStarter leaves base task/resource state retryable. The lifecycle test fake must expose `ensure` and `prompt`, not `agents` or `agent_start`.

- [ ] **Step 2: Run focused tests and verify the old implementation fails the interface**

Run: `uv run --project tools/herdr_task_lifecycle pytest tools/herdr_task_lifecycle/tests/commands/start/test_implementer.py tools/herdr_task_lifecycle/tests/commands/start/test_service.py -q`

Expected: FAIL until `implementer.py` consumes `AgentManager`.

- [ ] **Step 3: Implement the lifecycle adapter and wire the command**

Build `AgentTarget` from the state-recorded Workspace ID, root Pane ID, deterministic task name, and worktree. Call `manager.ensure`. Prompt when the task has no stored implementer reference, regardless of whether the lower service started or reused the live Agent; this preserves prompt-failure retries. Return `AgentReference(name=result.agent.name)` only after successful prompt.

Construct one `HerdrClient`, wrap it in `AgentManager`, and inject it into `TaskAgentStarter`. Catch `AgentManagementError` and `HerdrRuntimeError` at the lifecycle CLI boundary while preserving exit code 1 and `herdr-task:` prefix.

- [ ] **Step 4: Prove lifecycle no longer performs low-level Agent operations**

Run:

```bash
rg -n '\.(agents|agent_start|agent_prompt)\(' tools/herdr_task_lifecycle/src
```

Expected: no matches outside test-independent compatibility comments; lifecycle calls only `AgentManager.ensure` and `AgentManager.prompt`.

Run lifecycle pytest and Ruff; expected all pass.

- [ ] **Step 5: Commit**

```bash
git add tools/herdr_task_lifecycle
git commit -m "refactor: use Agent management from task lifecycle" -m "Keep Issue naming, prompts, and state policy in lifecycle while delegating Agent operations to herdr_agents." -m "Generated-by: Codex"
```

### Task 4: Update wrappers, installation contracts, and documentation

**Files:**
- Create: `bin/herdr-agents`
- Modify: `bin/start-herdr-agents.sh`
- Modify: `tests/install_test.sh`
- Modify: `tests/herdr_task_lifecycle_test.sh`
- Create: `tests/herdr_agents_test.sh`
- Create: `tests/herdr_runtime_test.sh`
- Modify: `README.md`
- Modify: `docs/HERDR-SYSTEMD-SETUP.md`
- Modify: `docs/HERDR-TASK-LIFECYCLE.md`
- Modify: `docs/superpowers/specs/2026-09-21-herdr-package-boundaries-design.md` only if implementation reveals a material, reviewed discrepancy

**Interfaces:**
- `bin/herdr-agents` runs `uv run --project tools/herdr_agents herdr-agents "$@"`.
- `start-herdr-agents.sh` retains readiness/flock and delegates through that wrapper or directly through the same project.
- Repository checks validate all three package boundaries and tolerate a valid ignored local config.

- [ ] **Step 1: Add failing shell contract checks**

Check that both new project metadata and locks exist, lifecycle declares both local dependencies, lifecycle no longer registers `herdr-agents`, the wrapper selects `tools/herdr_agents`, runtime has no CLI script, and docs show the dependency map. Replace `test ! -e .config/herdr/agents.toml` with:

```bash
git check-ignore -q .config/herdr/agents.toml
```

This confirms repository safety even when the user has created the local file.

- [ ] **Step 2: Run shell checks and verify they fail**

Run: `bash tests/install_test.sh && bash tests/herdr_agents_test.sh && bash tests/herdr_runtime_test.sh`

Expected: FAIL because wrappers/contracts are not complete.

- [ ] **Step 3: Implement wrappers and documentation**

Add the executable wrapper using the pinned mise uv path and update bootstrap to the independent project. Document:

```text
herdr_task_lifecycle -> herdr_agents -> herdr_runtime
                     -> herdr_runtime
                     -> herdr_task_state
```

Explain that lifecycle uses Agent operations without making Issue workers persistent, while `persistent` TOML reconciliation is the path that gives coordinators reboot/bootstrap persistence.

- [ ] **Step 4: Run package, shell, and help verification**

Run:

```bash
uv run --project tools/herdr_runtime pytest tools/herdr_runtime/tests -q
uv run --project tools/herdr_agents pytest tools/herdr_agents/tests -q
uv run --project tools/herdr_task_state pytest tools/herdr_task_state/tests -q
uv run --project tools/herdr_task_lifecycle pytest tools/herdr_task_lifecycle/tests -q
uv run --project tools/herdr_runtime ruff check tools/herdr_runtime/src tools/herdr_runtime/tests
uv run --project tools/herdr_agents ruff check tools/herdr_agents/src tools/herdr_agents/tests
uv run --project tools/herdr_task_state ruff check tools/herdr_task_state/src tools/herdr_task_state/tests
uv run --project tools/herdr_task_lifecycle ruff check tools/herdr_task_lifecycle/src tools/herdr_task_lifecycle/tests
bash tests/herdr_task_state_test.sh
bash tests/herdr_task_lifecycle_test.sh
bash tests/herdr_agents_test.sh
bash tests/herdr_runtime_test.sh
bash tests/install_test.sh
bin/herdr-task --help
bin/herdr-agents --help
git diff --check
```

Expected: all pass. Help checks must not start or reconcile live Agents.

- [ ] **Step 5: Commit**

```bash
git add bin tests README.md docs tools/herdr_agents tools/herdr_runtime tools/herdr_task_lifecycle
git commit -m "docs: document Herdr package responsibilities" -m "Wire the independent Agent command to its package and document how task-scoped and persistent Agents share the lower service." -m "Generated-by: Codex"
```

### Task 5: Whole-branch review and PR update

**Files:**
- Modify: only files required by findings
- Do not commit: `.superpowers/`

**Interfaces:**
- Consumes: all package and command contracts from Tasks 1–4.
- Produces: a clean pushed branch and updated PR #51, with no merge.

- [ ] **Step 1: Review the complete diff against the design**

Review `origin/main...HEAD` for dependency direction, duplicate domain logic, stale imports, accidentally broadened APIs, state compatibility, rollback catches, secret exposure, and user configuration handling. If no independent reviewer tool is available, record that the final review was a self-review.

- [ ] **Step 2: Fix findings test-first and rerun affected checks**

For each behavioral defect, first add a failing test in the owning package, then apply the smallest fix and run that package's pytest/Ruff plus affected shell checks.

- [ ] **Step 3: Run the complete Task 4 verification block on committed content**

Expected: all commands pass, worktree has no tracked changes, and untracked `.superpowers/` notes remain untouched.

- [ ] **Step 4: Push and verify the existing PR**

```bash
git push origin feat/issue-9-agent-management
GH_TOKEN="$(bin/get-github-app-token.py)" gh pr view 51 --json url,state,baseRefName,headRefName,reviewRequests
```

Expected: PR #51 remains open against main from `feat/issue-9-agent-management`, with `dodo5522` requested. Do not create another PR or merge.
