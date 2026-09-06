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
