# Blender modeling Skill

Issue #46 adds a small instruction layer over the existing `mcp-for-blender`
integration. There is no additional runtime package, controller, or script.

## Installation and connection

The tracked [.codex/skills/blender-modeling/SKILL.md](../.codex/skills/blender-modeling/SKILL.md)
is installed by the home-directory checkout at `/home/takashi`, following the
Herdr Skill convention. `install.sh` installs the dependencies, not a second
copy of the Skill. A feature worktree copy does not by itself install the Skill
into the active user's global Skill directory.

Follow [Blender MCP setup](../README.md#blender-mcp): run the installer as the
login user, enable `Interface: MCP for Blender` in Blender Preferences, and start
the add-on server from the 3D View's N sidebar. Restart the Codex session and
check that `blender-modeling` is available. Invoke it explicitly with
`$blender-modeling`, or request a Blender scene operation.

The configured MCP client uses `tools/blender_mcp/uv.lock` and connects to
`127.0.0.1:9876`. Verify the Blender-side listening address separately; the
client's host setting is not proof of the add-on's bind address. Keep the
endpoint local. A connection enables Python execution inside Blender and does
not sandbox that code.

## Example: a small stool

In a disposable scene, with an explicit empty output directory under the
current task root, ask:

> $blender-modeling: Blenderで高さ45 cmの木製スツールを作成してください。
> 座面は直径30 cm、脚は4本。既存のオブジェクトは残し、専用collectionに
> まとめてください。指定した出力先に stool.blend、stool.glb、preview.png
> を保存し、寸法と見た目を確認してください。

The agent inspects the scene, resolves units and output location, explains the
object plan, and saves a separate checkpoint before editing. It uses existing
MCP tools and short task-specific Blender operations to build the stool, checks
dimensions and a visual preview, and saves/exports the requested files. The
handoff should distinguish file existence, visual inspection, and any actual
reimport check. This example is an acceptance scenario, not a claim that a
live modeling run has already passed.

For existing work, a checkpoint such as `scene-before-stool.blend` must contain
current unsaved edits and must not overwrite an older backup. Inspection-only
requests such as「現在のsceneのobject数と寸法を調べて」do not require saving,
exporting, or geometry changes. Clarify missing export format/destination only
when export is needed.

## Recovery and verification

| Situation | Action |
| --- | --- |
| No Blender MCP tools | Check client configuration/session reload; report unavailable tools without claiming execution. |
| Add-on stopped or connection refused | Enable/start it in Blender and retry read-only inspection. |
| Operation fails or times out | Inspect current scene for partial changes; update the task's existing objects rather than blindly rerunning. |
| Backup fails | Resolve the save error before mutating the existing scene. |
| Export unsupported or destination missing | Resolve the format/path; do not silently substitute a different deliverable. |

The Skill's structural validation uses the existing `skill-creator`
`scripts/quick_validate.py`. Review the stool example, inspection-only request,
failed connection, failed checkpoint, and partial mutation scenarios against
the instructions. Keyword-matching tests cannot demonstrate correct modeling
behavior. A live MCP session and artifact inspection are still needed for an
end-to-end operational acceptance run.

## Public tooling assessment

Reviewed upstream README descriptions and GitHub license metadata on
2026-09-20. All four repositories below report MIT; these are repository-level
license observations, not a license audit of each dependency or asset.

| Source | Decision for #46 |
| --- | --- |
| [ahujasid/mcp-for-blender](https://github.com/ahujasid/mcp-for-blender) | Reuse the already locked 2.0.0 integration from #41 for scene inspection and Blender execution. |
| [newo-ether/blender-mcp](https://github.com/newo-ether/blender-mcp) | Has its own MCP/Skill setup; keep as a candidate because adopting it would require checking compatibility with the currently configured server. |
| [RobLe3/cc-blender-skill](https://github.com/RobLe3/cc-blender-skill) | Claude-oriented modeling Skill collection; useful future candidate, but host-specific tool conventions need assessment before adoption. |
| [ifBars/blender-agent-studio](https://github.com/ifBars/blender-agent-studio) | Broader Codex modeling/validation tooling; evaluate with #45/#43 if it removes the need for custom automation. |

No third-party Skill text or code is copied, vendored, or installed here. This
small locally written Skill records the repository's operating conventions.
Future adoption should pin a revision, inspect its instructions and dependencies,
preserve applicable notices, and establish an update policy. Imported models
and textures have their own licenses; an MCP project's MIT license does not
license those assets.

Use the [Blender Python API](https://docs.blender.org/api/current/) and select
the running Blender version's documentation when scripting; the `current` URL
can advance independently of this repository's pin.

## Related work

- [#41](https://github.com/dodo5522/ai-agent-home/issues/41): dependency/MCP installation.
- [#45](https://github.com/dodo5522/ai-agent-home/issues/45): reproducible modeling workflow.
- [#43](https://github.com/dodo5522/ai-agent-home/issues/43): automated artifact validation and safety gates.
- [#44](https://github.com/dodo5522/ai-agent-home/issues/44): model/sub-agent routing.

These future issues do not represent installed capabilities. The Skill uses
available Blender inspection tools and reports the checks actually performed.
