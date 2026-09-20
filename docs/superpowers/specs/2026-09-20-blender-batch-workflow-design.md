# Blender batch modeling workflow design

## Context

Issue #41 provides the mise-managed Blender 5.2.2 runtime. Issue #46 provides
the `blender-modeling` Skill. The server is headless, so this workflow uses
Blender's standard background CLI and retains the per-artwork Python script
with the final artifact set.

## Goals

- Turn a modeling request into a repeatable batch run with explicit inputs and
  outputs.
- Keep the generation/edit script as part of the final artwork handoff.
- Make clean reruns deterministic and prevent accidental changes to unrelated
  user files.
- Preserve checkpoints and partial results when a run fails.
- Establish a practical final set for `.py`, `.blend`, preview, optional exports,
  inputs, and `RUN.md`.
- Reuse the existing `bin/google-drive-uploader` only for explicitly requested
  final uploads.

## Non-goals

- Do not add an MCP server, GUI automation, virtual display, or Blender daemon.
- Do not add a general-purpose runner before repeated use demonstrates a need.
- Do not add artifact validation policy from #43 or model routing from #44.
- Do not automatically upload, overwrite, delete, or version Drive files.
- Do not put artwork or credentials in the repository.

## Per-artwork layout

The workflow uses a durable artwork directory outside the temporary Issue task
root. The exact directory can be chosen per task, but its managed contents use
this shape:

```text
artwork/
├── build.py
├── RUN.md
├── input/
├── output/
│   ├── model.blend
│   ├── preview.png
│   └── optional-export.glb
└── checkpoints/
```

`build.py` is the final generation/edit script. `RUN.md` records Blender
version, exact command, input dependencies, output paths, acceptance checks,
and manual changes that the script cannot reproduce. `input/` contains only
declared source assets. `output/` contains final deliverables. `checkpoints/`
contains pre-mutation or known-good saves while work is active; it is not part
of the final Drive set unless explicitly requested.

## Batch contract

New procedural scenes run with a clean factory state:

```bash
mise exec blender -- blender \
  --background \
  --factory-startup \
  --python-exit-code 1 \
  --python /absolute/path/artwork/build.py -- \
  /absolute/path/artwork/output
```

The script parses arguments after Blender's `--`, requires one output directory,
creates required output subdirectories, sets its own scene units/camera/lights,
and writes outputs only below the declared artwork directory. It exits nonzero
when generation, save, render, or requested export fails. It should print the
created paths and important scene facts needed by `RUN.md`.

Editing an existing scene is a separate mode. The source `.blend` is opened
with `--disable-autoexec`, inspected in a separate process, and copied to a
checkpoint before mutation. The edited result is saved to a new output path.
Unsaved edits in another GUI process are unavailable to the batch process and
must be saved by the user first.

## Reruns and failure recovery

- A clean procedural rerun starts from `--factory-startup`; it never accumulates
  objects from a previous output.
- A rerun after a partial failure preserves the last valid `.blend` and preview
  before replacing an output.
- An edit rerun targets objects/collections owned by the task by explicit names;
  it does not clear the entire source scene.
- Failed renders or exports leave the saved scene and logs available for repair.
- A nonzero exit, missing output, or failed reopen is a failed run even if some
  files were created.
- Manual GUI changes are recorded in `RUN.md` and are not claimed to be
  reproducible by `build.py`.

## Verification contract

Each accepted run checks:

1. command exit status;
2. expected `.blend` existence and nonzero size;
3. preview existence when requested;
4. requested export existence and nonzero size;
5. reopen of the saved `.blend` in background mode;
6. scene facts relevant to the request, such as dimensions, units, object names,
   and object count.

Visual inspection is required when appearance is part of acceptance. A process
exit code alone does not establish visual quality. Renderer and GPU availability
must be treated as environment inputs.

## Final retention and Drive handoff

After acceptance, retain only the final `build.py`, `.blend`, preview, requested
exports, required input assets, and `RUN.md` as the standard handoff set.
Artwork Git history is optional and not required. The set must be copied to a
durable location before the temporary Issue task root is cleaned up.

For an explicit upload request, use only:

```bash
bin/google-drive-uploader upload --folder-id FOLDER_ID \
  /absolute/path/build.py \
  /absolute/path/model.blend \
  /absolute/path/preview.png \
  /absolute/path/RUN.md
```

Add requested exports and input assets as explicit paths. The uploader creates
new files and verifies their returned name and size; it does not overwrite or
delete an existing same-named Drive file. If an upload partially succeeds,
record returned IDs/links and send only missing files on retry. Never upload
credentials, tokens, private keys, or hidden secrets.

## Deliverable

The implementation will provide a documented workflow and one deterministic
sample artifact under test-managed temporary storage. It will not create a
durable user artwork or upload anything to Drive automatically.
