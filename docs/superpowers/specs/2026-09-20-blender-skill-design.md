# Blender modeling Codex Skill design

## Superseding decision: batch execution and final artifact retention

The user subsequently chose standard headless Blender batch execution and
removal of the MCP path. This decision supersedes the MCP architecture below,
which is retained as design history. Remove the Blender MCP client registration,
locked dependency metadata and installer phases; retain Blender and OS libraries.
Use a small instruction-only Skill with per-artwork Python executed by Blender.
Keep the final Python, blend, preview, execution note and required assets together;
artwork version control is unnecessary. Explicitly requested Drive uploads use
the existing uploader; it creates files rather than replacing prior versions.
No artwork has been generated or uploaded as part of this implementation task.

## Context

Issue #41 provides the repository-managed Blender 5.2.2 runtime, the locked
`mcp-for-blender` project, and the localhost-only Codex MCP registration. Issue
#46 adds the reusable operating instructions that make that integration useful
for modeling work.

The repository should prefer existing Blender MCP capabilities and public
Skills over custom automation. The Skill is therefore an instruction layer,
not a second Blender controller or validation framework.

## Goals

- Activate for requests that create, edit, inspect, render, or export Blender
  scenes and assets.
- Give an agent a repeatable sequence from requirements clarification through
  delivery.
- Make scene inspection and incremental changes the default before mutation.
- Keep user data safe through backup, scope, and arbitrary-Python warnings.
- Document the existing MCP setup and point to authoritative Blender API
  documentation without vendoring external code.
- Record public Skill/tool candidates and their adoption status, provenance,
  and license considerations.

## Non-goals

- Do not implement model or sub-agent routing; that belongs to #44.
- Do not implement artifact validation or safety enforcement; that belongs to
  #43. This Skill can require those checks when available and document the
  current trust boundary.
- Do not add a custom Blender daemon, Python package, or MCP server.
- Do not vendor a third-party Skill or plugin in this issue.
- Do not promise unattended arbitrary Python execution or destructive scene
  edits.

## Repository structure

```text
.codex/skills/blender-modeling/SKILL.md
docs/BLENDER-SKILL.md
tests/install_test.sh
README.md
```

The Skill is installed by being present in the repository's `.codex/skills`
tree, matching the existing Herdr Skill convention. No new runtime dependency
is required.

## Skill behavior

The Skill should instruct the agent to:

1. Clarify the target, style, scale, required deliverables, and acceptance
   checks.
2. Inspect the current Blender scene and identify the objects/materials/camera
   that are in scope.
3. Propose a short scene plan before making material changes.
4. Create a backup or save checkpoint before mutating an existing user scene.
5. Prefer small, named, repeatable MCP Python operations over one opaque script.
6. Inspect the result after each meaningful operation and correct failures.
7. Save the `.blend`, render a useful preview when requested, and export only
   the requested formats.
8. Report paths, limitations, and any manual Blender UI steps required.

The Skill must explicitly distinguish read-only inspection, reversible scene
changes, and destructive or arbitrary-code operations. It must require user
confirmation when the requested action could overwrite or delete unrelated
user data.

## Public tooling policy

The initial implementation will use the repository's existing `mcp-for-blender`
integration from #41. Public candidates are references, not bundled runtime
dependencies:

- `newo-ether/blender-mcp` documents a Codex-compatible Blender MCP Skill and
  MCP workflow: https://github.com/newo-ether/blender-mcp
- `roble3/cc-blender-skill` provides a focused Blender modeling Skill example:
  https://github.com/RobLe3/cc-blender-skill
- `ifBars/blender-agent-studio` is a broader Codex plugin candidate for future
  workflow/validation work: https://github.com/ifBars/blender-agent-studio
- Blender's Python API documentation is the authoritative scripting reference:
  https://docs.blender.org/api/current/

The repository will not copy code from these projects in this issue. The
operator documentation will record what was inspected, what was adopted or
rejected, and why. Any future vendoring requires an explicit license and update
policy review.

## Documentation and test contract

`docs/BLENDER-SKILL.md` will explain installation assumptions, activation
examples, the end-to-end operating sequence, safety boundaries, and public
tooling provenance. `tests/install_test.sh` will assert that the Skill exists
and contains the activation, planning, inspection, checkpoint, MCP execution,
verification, export, and safety guidance. These tests are contract checks;
they do not launch Blender or mutate a user scene.

## Failure handling

The Skill should stop and report rather than silently continue when:

- Blender MCP is unavailable or the Blender-side add-on is not running.
- The current scene cannot be inspected reliably.
- A requested operation would overwrite an unscoped file or scene.
- A generated operation fails verification.
- The user has not specified a required export format or destination.

It should preserve the last known checkpoint and provide the next manual or
agent action needed to resume.

## Acceptance criteria

- A focused `SKILL.md` has clear activation criteria and operating instructions.
- The Skill can guide a small end-to-end modeling task using the existing MCP.
- Planning, execution, verification, and delivery are distinct phases.
- No new third-party runtime code is introduced.
- The public tooling decision and provenance are documented.
- Skill contract tests and the existing test suite pass.
