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

- Create Git worktrees under `/home/takashi/work/worktrees/`.
- Clone repositories under `/home/takashi/work/repos/`.
- Create agent-managed temporary files and directories under `/home/takashi/work/tmp/`.
- Do not create these resources outside `/home/takashi/work` unless the user explicitly requests another location or a tool requires a system-managed temporary location.
- Before deleting temporary data, verify that the resolved target path is contained within `/home/takashi/work`.

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
