## Git workflow

When making changes in this repository:

- Never commit or push directly to `main`.
- Always create a feature branch using the `feat/*` naming convention.
- Commit all intended changes before pushing.
- Push the feature branch to `origin`.
- Create a Pull Request targeting `main`.
- Request review from `dodo5522`.
- Never merge the Pull Request yourself.
- Wait for human review and approval before merge.

## Pull Request updates

When review feedback is received:

- Apply the requested changes on the existing feature branch.
- Run relevant tests and checks.
- Commit the fixes.
- Push the updated branch.
- Do not create a new Pull Request unless explicitly requested.
- Do not merge the Pull Request.

## After Pull Request merge

When the user reports that a Pull Request has been merged:

- Switch to `main`.
- Pull the latest changes from `origin/main` using fast-forward only.
- Confirm that the local `main` matches `origin/main`.
- Follow the cleanup plan, approval, execution, and retry process in
  [`docs/HERDR-TASK-LIFECYCLE.md`](docs/HERDR-TASK-LIFECYCLE.md).

## Workspace location

When creating additional working data:

- Create a unique task root under `/home/takashi/work/tasks/<task-id>/`.
- Create a `.codex-task-root` marker file directly inside the task root.
- Place all Git worktrees, cloned repositories, and agent-managed temporary data for that task inside its task root, using subdirectories such as `worktree/`, `repo/`, and `tmp/`.
- Do not create these resources outside the task root unless the user explicitly requests another location or a tool requires a system-managed temporary location.
- Keep the task root while its Pull Request is open or may still receive review updates.

## Task workspace cleanup

The canonical resource roles, retention triggers, managed-resource boundary,
and exact cleanup procedure are in
[`docs/HERDR-TASK-LIFECYCLE.md`](docs/HERDR-TASK-LIFECYCLE.md). Keep the Tab,
worktree, task root, and state mapping while a Pull Request is open or under
review. For non-PR work, wait for explicit user completion confirmation.
Always show a fresh `herdr-task cleanup --plan`, obtain human approval, and use
the plan's exact task root for guarded execution. Never clean up unmanaged or
another task's resources.

## Commit policy

When you create a Git commit:

- Use a clear, concise, conventional commit subject.
- Add a blank line after the commit body.
- Always append this trailer:

Generated-by: Codex

Example:

feat: add Herdr systemd bootstrap

Add user services for Herdr and Codex session restoration.

Generated-by: Codex

## Security

- Never commit secrets, tokens, private keys, `.pem` files, or credentials.
- Do not embed GitHub access tokens in Git remote URLs.
- Use the configured Git credential helper or GitHub App authentication.

## Implementation language and dependency policy

When adding a tool or automation with non-trivial logic:

- Implement it in the Python version managed by mise and declared in `.config/mise/config.toml`.
- Keep shell scripts limited to simple orchestration, argument/environment setup, or thin wrappers around Python tools.
- Prefer Python standard-library modules whenever they are sufficient.
- If a well-established third-party package materially reduces the implementation, manage it with `uv`, pin exact dependency versions, and commit the resulting project metadata and lockfile.
- Install and manage `uv` through mise; keep its version pinned in `.config/mise/config.toml` (the current approved pin is `0.12.11`).
- Do not install project dependencies ad hoc with a system `pip`; use the mise-managed Python and the repository's documented `uv` workflow.
- Make Python tools directly runnable with `uvx` (or the equivalent `uv run` project command).
- Use pytest for tests, shared setup through fixtures, and Ruff for formatting and linting.
- Keep each tool's runtime and development dependencies in that tool's own `pyproject.toml` and `uv.lock` under `tools/<tool-name>/`.
