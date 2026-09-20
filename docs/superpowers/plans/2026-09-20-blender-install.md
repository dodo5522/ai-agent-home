# Blender installation bootstrap plan

## Goal

Make `ai-agent-home` install the pinned Blender runtime and the locked
`mcp-for-blender` dependency needed by the planned Codex Blender skill. Keep
the installer repeatable, dry-run friendly, and explicit about the security
boundary of the Blender socket add-on.

## Design

- `.config/mise/config.toml` owns the Blender version (`5.2.2`) alongside the
  existing Codex, Herdr, Node, Python, and uv tools.
- Ubuntu runtime libraries required by the prebuilt Blender binary are
  installed explicitly: `libgl1`, `libsm6`, `libx11-6`, `libxext6`,
  `libxfixes3`, `libxi6`, `libxrender1`, `libxrandr2`, `libxinerama1`, and
  `libxxf86vm1`. These are runtime packages, not Blender source-build
  `-dev` dependencies.
- `tools/blender_mcp/pyproject.toml` owns the third-party Python dependency and
  requires Python 3.11 because the upstream MCP documentation recommends a
  uv-managed 3.11 interpreter for compatibility.
- `tools/blender_mcp/uv.lock` pins the complete Python dependency graph.
- `install.sh` runs `mise install`, then runs the locked project with
  `mise exec uv -- uv sync --locked` and installs the Blender add-on through
  `uv run --project tools/blender_mcp mcp-for-blender install-addon`.
- `.codex/config.toml` registers the MCP server through the same locked
  project, binds it to `127.0.0.1:9876`, and disables telemetry explicitly.
- `tests/install_test.sh` verifies the installer contract without installing
  software. The real installer verification checks Blender, uv, the locked
  project, the MCP CLI, and a headless Blender launch after installation.

## Task 1: Add failing installer contract tests

Files:

- Modify: `tests/install_test.sh`

Add tests that fail on the base branch because they require:

- `blender = "5.2.2"` in `.config/mise/config.toml`.
- `tools/blender_mcp/pyproject.toml` with an exact `mcp-for-blender==2.0.0`
  dependency and Python 3.11 compatibility.
- `tools/blender_mcp/uv.lock`.
- Dry-run output containing the locked uv sync and add-on installation phases.
- The apt package command containing the Blender OpenGL, X11, and session
  runtime libraries.
- Verification output containing Blender and the MCP CLI checks.
- `.codex/config.toml` containing a localhost-only Blender MCP server using the
  locked project and `UV_PYTHON_PREFERENCE=only-managed`.

Run `bash tests/install_test.sh` and confirm the new assertions fail for the
expected missing files or strings before adding implementation files.

## Task 2: Add locked Blender MCP dependency metadata

Files:

- Create: `tools/blender_mcp/pyproject.toml`
- Create: `tools/blender_mcp/uv.lock`
- Modify: `.config/mise/config.toml`

Create a non-package uv project named `ai-agent-home-blender-mcp`, requiring
Python `>=3.11,<3.12` and exactly `mcp-for-blender==2.0.0`. Generate and commit
the lockfile with the mise-managed uv executable. Add Blender `5.2.2` to the
mise tools table. Add the runtime apt packages listed in the design to the
existing Ubuntu package installation command. Do not add compiler or `-dev`
packages solely for the prebuilt mise binary.

Run the focused metadata assertions and `mise exec uv -- uv lock --check
--project tools/blender_mcp`.

## Task 3: Extend the installer

Files:

- Modify: `install.sh`
- Modify: `tests/install_test.sh`

Add a helper that runs commands through the repository mise config and the
locked Blender MCP project. After the existing `mise install` phase:

1. Run `uv sync --locked --project tools/blender_mcp`.
2. Run `uv run --project tools/blender_mcp mcp-for-blender install-addon` with
   `UV_PYTHON_PREFERENCE=only-managed`.
3. Verify `blender --version`, a headless factory-startup invocation,
   `uv --version`, the locked project, and `mcp-for-blender --help`.

The dry-run path must print these exact phases without invoking uv, Blender, or
the add-on installer. The normal path must remain a login-user operation; no
root privileges may be used for user-level Blender or uv state.

Run the new focused install tests, then the complete `bash tests/install_test.sh`
suite.

## Task 4: Register and document the integration

Files:

- Modify: `.codex/config.toml`
- Modify: `README.md`

Register a `blender` MCP server that runs the locked project, uses a managed
Python interpreter, sets `BLENDER_HOST=127.0.0.1` and `BLENDER_PORT=9876`, and
sets `DISABLE_TELEMETRY=true`. Document the required Blender-side enable/start
step, the Codex restart, verification commands, backups, localhost-only
network policy, and the fact that the add-on can execute Python in Blender.

Run TOML/config assertions and the complete install test suite.

## Review focus

- A dry-run must not create an uv environment or modify Blender add-ons.
- A lockfile must prevent an unreviewed transitive dependency update.
- The installer must not run as root or open the Blender socket beyond
  localhost.
- Re-running the add-on install must use the upstream supported installer and
  must not delete the existing scene or user files.
- Existing non-Blender install behavior and tests must remain unchanged.
