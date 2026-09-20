# Blender Modeling Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a repository-managed Blender modeling Skill that guides agents through safe, repeatable use of the existing `mcp-for-blender` integration without adding custom runtime code.

**Architecture:** Install the Skill as `.codex/skills/blender-modeling/SKILL.md`, following the existing Herdr Skill convention. Put user-facing setup, workflow, public-tool provenance, and trust-boundary guidance in `docs/BLENDER-SKILL.md`; link it from README. Extend the existing shell contract tests to verify required guidance and file placement, without launching Blender or mutating user files.

**Tech Stack:** Markdown, Bash contract tests, existing Blender 5.2.2 and `mcp-for-blender` MCP integration.

**Spec:** `docs/superpowers/specs/2026-09-20-blender-skill-design.md`

## Global Constraints

### Execution adjustment (2026-09-20)

Native execution uses the existing skill-creator structural validator and a
scenario-based author review instead of Tasks 1–3's prose substring assertions.
Those assertions mirror wording rather than observable behavior, and the
planned sample Skill does not even contain several asserted phrases. No new
test code or runtime helpers are needed for this instruction-only change.
The existing installer suite remains the regression check. The full unrelated
Python suites in Task 4 are replaced with that focused check and diff hygiene.
This adjustment preserves the specified deliverables and records the departure
from the original test plan; no RED/GREEN behavioral test is claimed.

The validation dependency PyYAML 6.0.3 is used only in an ephemeral uv
environment for the existing checker, not added to project runtime dependencies.
Live MCP modeling remains an operational acceptance step; the author scenario
review is not an end-to-end modeling test.

- Reuse the repository's existing `mcp-for-blender` integration from #41.
- Do not add a custom Blender daemon, Python package, or MCP server.
- Do not vendor third-party Skills or plugins in this issue.
- Keep model/sub-agent routing in #44 and artifact validation/safety enforcement in #43.
- Require backup/checkpoint and user confirmation before destructive or unscoped scene/file changes.
- Contract tests must not launch Blender or mutate a user scene.

## Review Focus

- A request that only inspects a scene must not be presented as requiring mutation; pin the read-only inspection phase in the Skill contract test (Task 1).
- An existing user scene must receive a checkpoint before mutation; pin checkpoint and overwrite confirmation guidance (Task 1).
- An unavailable or stopped MCP/add-on must stop the workflow with a recovery action; pin the failure guidance (Task 1).
- An unspecified export format or destination must be clarified before export; pin the delivery guidance (Task 1).
- A public Skill/plugin must not be silently copied into the repository; pin provenance and no-vendoring guidance (Task 1).

### Task 1: Add the Blender Skill contract tests

**Files:**
- Modify: `tests/install_test.sh`

**Interfaces:**
- Consumes: repository paths resolved from `REPO_ROOT`.
- Produces: shell assertions for `.codex/skills/blender-modeling/SKILL.md` and `docs/BLENDER-SKILL.md` that later tasks must satisfy.

- [ ] **Step 1: Write the failing tests**

Add constants near the existing Skill constants:

```bash
BLENDER_SKILL="$REPO_ROOT/.codex/skills/blender-modeling/SKILL.md"
BLENDER_SKILL_DOC="$REPO_ROOT/docs/BLENDER-SKILL.md"
```

Add this test before the existing test invocations:

```bash
test_blender_skill_is_installed_with_modeling_contract() {
    local skill doc

    if [[ ! -f $BLENDER_SKILL ]]; then
        fail "Blender modeling Skill is installed"
        return
    fi
    pass "Blender modeling Skill is installed"
    skill=$(<"$BLENDER_SKILL")

    assert_contains "$skill" 'When to use this Skill' "Skill documents activation"
    assert_contains "$skill" 'requirements clarification' "Skill clarifies requirements"
    assert_contains "$skill" 'read-only scene inspection' "Skill starts with read-only inspection"
    assert_contains "$skill" 'checkpoint' "Skill requires a checkpoint before mutation"
    assert_contains "$skill" 'mcp-for-blender' "Skill uses the existing MCP integration"
    assert_contains "$skill" 'inspect after each meaningful operation' "Skill requires iterative inspection"
    assert_contains "$skill" 'export' "Skill documents artifact export"
    assert_contains "$skill" 'user confirmation' "Skill requires confirmation for destructive changes"
    assert_contains "$skill" 'do not' "Skill states safety boundaries"

    if [[ ! -f $BLENDER_SKILL_DOC ]]; then
        fail "Blender modeling Skill documentation exists"
        return
    fi
    pass "Blender modeling Skill documentation exists"
    doc=$(<"$BLENDER_SKILL_DOC")
    assert_contains "$doc" '127.0.0.1:9876' "Skill documentation uses the configured MCP endpoint"
    assert_contains "$doc" 'Blender Python API' "Skill documentation links the Blender API"
    assert_contains "$doc" 'newo-ether/blender-mcp' "Skill documentation records public tooling provenance"
    assert_contains "$doc" 'Do not vendor' "Skill documentation records the no-vendoring policy"
    assert_contains "$doc" 'backup' "Skill documentation explains backups"
}
```

Register `test_blender_skill_is_installed_with_modeling_contract` with the other test calls at the bottom of the file.

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `bash tests/install_test.sh`

Expected: the new assertions fail because the Skill and documentation files do not exist; existing tests remain green.

- [ ] **Step 3: Commit the failing contract**

```bash
git add tests/install_test.sh
git commit -m "test: define Blender modeling Skill contract"
```

### Task 2: Add the executable Blender modeling Skill

**Files:**
- Create: `.codex/skills/blender-modeling/SKILL.md`

**Interfaces:**
- Consumes: the existing Codex Blender MCP server named `blender` from `.codex/config.toml`.
- Produces: activation and operating instructions consumed by Codex when a Blender modeling request matches.

- [ ] **Step 1: Write the Skill content**

Create a focused Markdown Skill with these sections and behavior:

```markdown
---
name: blender-modeling
description: Use for creating, editing, inspecting, rendering, or exporting Blender scenes and assets through the configured Blender MCP integration.
---

# Blender Modeling

## When to use this Skill

Activate for requests to model, modify, inspect, render, or export a Blender scene or asset. Do not activate for general 3D advice that does not touch Blender.

## Operating contract

1. Clarify the target, style, scale, existing-scene scope, required deliverables, output destination, and acceptance checks.
2. Use the `blender` MCP server to perform read-only scene inspection first. Identify in-scope objects, materials, camera, collections, and the current file path.
3. Present a short scene plan and call out whether the operation is read-only, reversible, or destructive.
4. Before changing an existing scene, save a checkpoint or backup in an explicit destination. Do not overwrite unrelated files or delete unscoped objects without user confirmation.
5. Prefer small, named, repeatable Blender Python operations. After each meaningful operation, inspect the affected objects and report failures before continuing.
6. Save the managed `.blend` file, render a preview when requested, and export only the formats and destinations the user specified.
7. Report created files, manual Blender UI steps, limitations, and the next recovery action if the workflow stops.

## Safety boundary

The Blender add-on can execute Python inside Blender. Treat generated code as untrusted: review file, process, network, and deletion operations; require user confirmation for destructive or unscoped actions; and preserve a checkpoint before mutation.

If MCP is unavailable, the add-on is not running, the scene cannot be inspected, or the export destination is unspecified, stop and ask for the missing action or information.

## Responsibility boundaries

Do not select models or sub-agents here; follow the routing policy from #44 when available. Do not claim that this Skill validates polygon counts, topology, or exports; use #43's validator when available and report that validation is not yet installed otherwise.
```

The final file may refine wording, but it must preserve the explicit activation, inspection, planning, checkpoint, MCP, iteration, export, failure, and safety behavior above. It must contain no custom code or third-party copied content.

- [ ] **Step 2: Run the focused contract test**

Run: `bash tests/install_test.sh`

Expected: the Blender Skill assertions pass; any remaining failures are only for the documentation file from Task 3.

- [ ] **Step 3: Commit the Skill**

```bash
git add .codex/skills/blender-modeling/SKILL.md
git commit -m "feat: add Blender modeling Codex Skill"
```

### Task 3: Add operator documentation and README guidance

**Files:**
- Create: `docs/BLENDER-SKILL.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: the Skill behavior from `.codex/skills/blender-modeling/SKILL.md` and the existing MCP setup from #41.
- Produces: user-facing setup, usage, provenance, and safety guidance linked from README.

- [ ] **Step 1: Add documentation that satisfies the contract**

Create `docs/BLENDER-SKILL.md` with:

- prerequisites: run `install.sh`, enable the Blender add-on, start the MCP panel, and restart Codex;
- endpoint: `127.0.0.1:9876` and the existing locked `tools/blender_mcp` project;
- a small example request and expected phases: clarify, inspect, plan, checkpoint, execute, inspect, save/export, report;
- a clear distinction between read-only inspection, reversible changes, and destructive changes;
- backup/checkpoint examples and a rule to clarify output format and destination before export;
- recovery instructions for MCP unavailable, add-on stopped, failed operation, and missing destination;
- public tooling provenance for `newo-ether/blender-mcp`, `roble3/cc-blender-skill`, `ifBars/blender-agent-studio`, and the Blender Python API;
- an explicit statement that these projects are references only and are not vendored or automatically installed;
- links to #41, #43, and #44 for the dependency, validation, and routing boundaries.

Add a short README subsection under the existing `Blender MCP` section linking to `docs/BLENDER-SKILL.md` and explaining that the Skill is instruction-only and reuses the configured MCP.

- [ ] **Step 2: Run the complete shell contract suite**

Run: `bash tests/install_test.sh`

Expected: all tests pass, including the new Skill and documentation assertions.

- [ ] **Step 3: Check Markdown and diff hygiene**

Run: `git diff --check`

Expected: no whitespace errors.

- [ ] **Step 4: Commit the documentation**

```bash
git add docs/BLENDER-SKILL.md README.md
git commit -m "docs: document Blender modeling Skill"
```

### Task 4: Run the full verification suite

**Files:**
- No source changes expected; only test output and the SDD ledger are generated.

**Interfaces:**
- Consumes: all committed files from Tasks 1–3.
- Produces: verified branch ready for review.

- [ ] **Step 1: Run all repository checks relevant to the change**

Run:

```bash
set -e
bash -n install.sh
bash tests/install_test.sh
bash tests/herdr_task_state_test.sh
bash tests/herdr_task_lifecycle_test.sh
uv run --project tools/herdr_task_state --group dev pytest tools/herdr_task_state/tests
uv run --project tools/herdr_task_lifecycle --group dev pytest tools/herdr_task_lifecycle/tests
git diff --check main..HEAD
```

Expected: every command exits zero; no Blender process or user scene is mutated by the tests.

- [ ] **Step 2: Commit only if verification requires a test/documentation correction**

If a correction is required, add a focused failing assertion first, run it to observe the failure, make the minimal correction, rerun the full suite, and use a conventional commit with the `Generated-by: Codex` trailer. If no correction is required, do not create an empty commit.
