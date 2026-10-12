# GitHub App Private-Key Separation Design

## Goal

Keep the long-lived GitHub App private key inaccessible to Codex while
preserving non-interactive Git and GitHub CLI access through short-lived
installation access tokens.

## Scope

This design replaces the current same-user private-key reader with a local
token broker. It covers the installer, systemd units, token client, credential
helper integration, operator migration, and tests. It does not change GitHub
App permissions, store access tokens, or expose a general signing service.

## Trust boundary

The broker is a system service that runs as `root`. Its executable, unit
files, App configuration, and private key are root-owned. Codex runs as the
ordinary login user and can only connect to the broker's Unix-domain socket;
it cannot read, replace, or execute the privileged implementation.

The installer will place these privileged files in root-controlled locations:

| Item | Path | Owner and mode |
| --- | --- | --- |
| Broker implementation | `/usr/local/lib/ai-agent-home/github_app_token_broker.py` | `root:root`, `0755` |
| App configuration | `/etc/ai-agent-home/github-app/config` | `root:root`, `0600` |
| App private key | `/etc/ai-agent-home/github-app/private-key.pem` | `root:root`, `0600` |
| Service and socket units | `/etc/systemd/system/github-app-token.{service,socket}` | `root:root`, `0644` |
| Runtime socket | `/run/github-app-token/token.sock` | `root:github-app-token`, `0660` |

The installer creates a dedicated `github-app-token` system group and adds
`takashi` to it. A new login session is required before group membership is
effective. Socket access intentionally grants the ability to obtain a
short-lived installation token; it does not grant filesystem or process access
to the key. No other users are added to that group.

## Token broker

`github-app-token.socket` owns a single Unix stream socket at
`/run/github-app-token/token.sock` and activates
`github-app-token.service` on demand. The service accepts exactly one request:
the ASCII line `GET\n`. It rejects all other requests without reflecting their
content, so callers cannot choose an App, installation, URL, key path, or JWT
claims.

For a valid request, the service reads its root-only configuration and key,
creates an RS256 App JWT, and exchanges it with GitHub's fixed installation
access-token endpoint. It returns only the installation token followed by one
newline. The response is never cached or written to disk. The broker uses
short, bounded read, write, connect, and HTTP timeouts.

The implementation uses the system Python and the distro `cryptography`
package, rather than any interpreter or package directory writable by the login
user. It uses the Python standard library for the Unix socket and HTTPS
request. Error messages are stable, generic, and contain no request body,
response body, JWT, token, or path to secret material.

The unit uses a minimal environment and service hardening appropriate for an
on-demand network client. Its writable locations are limited to the runtime
directory created for the socket. It does not log successful token issuance or
tokens. Error output is generic, so journal entries do not include credentials
or GitHub response bodies.

## Unprivileged client compatibility

`bin/get-github-app-token.py` becomes an unprivileged Unix-socket client. It
sends the fixed request, validates that the response is one non-empty line, and
writes the token alone to standard output. Failures use generic diagnostics on
standard error and do not print server responses. It never reads a private key,
App configuration, or HTTP endpoint.

The client keeps its existing executable name and output contract. Therefore:

- `bin/git-credential-helper` continues to invoke it for `https://github.com`
  and returns the token as Git's password without persisting it.
- Existing `GH_TOKEN="$(bin/get-github-app-token.py)" gh ...` calls continue
  to work.
- `herdr_task_lifecycle.identity` continues to obtain the token through that
  client when `GH_TOKEN` is not already supplied.

## Installation and migration

The installer adds the required system packages, installs the root-owned
broker and systemd unit files, creates the dedicated group, installs the
root-owned configuration directory, enables the socket, and verifies the
unprivileged client can reach it. It never copies, prints, or logs a private
key.

The documented setup has the operator create `/etc/ai-agent-home/github-app`,
move the pre-existing key and App IDs into that directory with `sudo install`,
and apply the required ownership and modes. The installer must refuse to
silently use the legacy `~/.config/github-app/private-key.pem` path. Operators
remove the legacy key only after a successful token and Git verification. The
repository continues to ignore private-key files and never contains key or
token material.

## Failure handling

- Missing socket, inaccessible socket, malformed response, or broker failure:
  the client exits nonzero with a generic diagnostic and emits no token.
- Invalid root-owned configuration or key, network failure, or GitHub API
  rejection: the broker returns a generic failure and logs no sensitive
  payload.
- A caller-supplied `GH_TOKEN` remains supported by lifecycle code and bypasses
  the client, preserving testability and explicit operator overrides.
- The socket's group permission is the sole intentional unprivileged access
  path; direct reads of privileged paths must fail for `takashi`.

## Verification

Tests will exercise the real client protocol against a local Unix socket,
including successful token delivery, unavailable socket, malformed response,
and failure response. They will verify the credential helper delegates to the
client without storing credentials. Installer tests will verify the generated
commands and files establish root ownership, required modes, the dedicated
group, systemd socket activation, and no legacy private-key path.

Operator verification will check that the login user cannot read the new key,
the client obtains a token without displaying it, and `git fetch` and `git
push` use the credential helper successfully. Journal inspection must show no
token, JWT, key, or HTTP response payload.
