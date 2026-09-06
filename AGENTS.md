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

## Workspace location

When creating additional working data:

- Create a unique task root under `/home/takashi/work/tasks/<task-id>/`.
- Create a `.codex-task-root` marker file directly inside the task root.
- Place all Git worktrees, cloned repositories, and agent-managed temporary data for that task inside its task root, using subdirectories such as `worktree/`, `repo/`, and `tmp/`.
- Do not create these resources outside the task root unless the user explicitly requests another location or a tool requires a system-managed temporary location.
- Keep the task root while its Pull Request is open or may still receive review updates.

## Task workspace cleanup

When the user reports that a Pull Request has been merged, first complete the post-merge `main` synchronization, then clean up that task's workspace. For work without a Pull Request, clean it up after the user confirms that the task is complete.

Before cleanup:

- Resolve and display the exact task-root path.
- Confirm that the resolved path is strictly below `/home/takashi/work/tasks/` and is neither `/home/takashi/work` nor `/home/takashi/work/tasks` itself.
- Confirm that the `.codex-task-root` marker exists directly inside the resolved task root.
- Confirm that no Git worktree registered by any repository is actively using a path inside the task root.
- Request one approval for recursively deleting the entire task root; do not request approval separately for each contained file or directory.

After approval, delete the task root in one operation and report the deleted path and whether recovery is possible.

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
