# GitHub App Private-Key Separation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Isolate the GitHub App private key in a root-owned systemd token broker while preserving Git and GitHub CLI token use for Codex.

**Architecture:** A root-owned Python broker, started by a systemd Unix socket, reads root-only App material and exchanges a fixed GitHub App JWT for an installation token. The existing token-helper name becomes a standard-library socket client, so callers receive only short-lived tokens and never read the private key.

**Tech Stack:** Ubuntu system Python 3.12+, distro `python3-cryptography`, Python standard library, systemd system units, Bash installer, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-10-12-github-app-private-key-separation-design.md`

## Global Constraints

- The broker runs with `/usr/bin/python3`; it must not use mise, user-owned virtual environments, or user-owned import paths.
- RSA signing uses Ubuntu-managed `python3-cryptography`; socket and HTTPS handling use the standard library.
- Private key and App configuration live only at `/etc/ai-agent-home/github-app/`, owned by `root:root` with mode `0600`.
- Broker source and systemd unit files installed outside the repository are root-owned; Codex has no write path to them.
- The only unprivileged capability is access to `/run/github-app-token/token.sock` through the dedicated `github-app-token` group.
- The protocol accepts only `GET\n`, emits a token plus newline on success, and never logs or reports credentials, JWTs, HTTP bodies, or private-key contents.
- Do not persist installation tokens, add credentials to Git remotes, or change the existing `bin/get-github-app-token.py` stdout contract.
- All commits use a conventional subject and include the `Generated-by: Codex` trailer.

## Review Focus

- A malformed or oversized socket request is rejected without echoing attacker-controlled content.
- A socket response with whitespace, multiple lines, or an empty line never becomes a `GH_TOKEN`.
- A GitHub API error body that contains sensitive data never reaches a journal or client diagnostic.
- The installed service never imports an interpreter, script, module, or configuration writable by `takashi`.
- A legacy home-directory private key is not an operational fallback after migration.

## File Structure

| File | Responsibility |
| --- | --- |
| `tools/github_app_token_broker/src/github_app_token_broker/broker.py` | Root-only request handling, JWT signing, GitHub token exchange, and sanitized failures. |
| `tools/github_app_token_broker/src/github_app_token_broker/client.py` | Unprivileged Unix-socket client contract shared by wrapper and tests. |
| `tools/github_app_token_broker/pyproject.toml` | pytest/Ruff development environment and external Ubuntu runtime-dependency note. |
| `tools/github_app_token_broker/tests/` | Local socket protocol, validation, and no-secret diagnostic tests. |
| `systemd/github-app-token.service` | Root systemd service for the installed broker. |
| `systemd/github-app-token.socket` | Group-restricted, on-demand Unix socket. |
| `bin/get-github-app-token.py` | Stable CLI wrapper around the socket client. |
| `install.sh` | Root-owned installation, group setup, migration checks, and socket enablement. |
| `tests/install_test.sh` | Observable installer dry-run and installed-artifact assertions. |
| `README.md` | Operator setup, migration, verification, and secret-safe troubleshooting. |
| `docs/HERDR-TASK-LIFECYCLE.md` | Advance the recommended Issue order after the implementation is PR-ready. |

### Task 1: Implement and test the token broker protocol

**Files:**
- Create: `tools/github_app_token_broker/pyproject.toml`
- Create: `tools/github_app_token_broker/src/github_app_token_broker/__init__.py`
- Create: `tools/github_app_token_broker/src/github_app_token_broker/broker.py`
- Create: `tools/github_app_token_broker/src/github_app_token_broker/client.py`
- Create: `tools/github_app_token_broker/tests/test_broker.py`
- Create: `tools/github_app_token_broker/tests/test_client.py`
- Create: `tools/github_app_token_broker/uv.lock`

**Interfaces:**
- Consumes: root-only fixed `config` and `private-key.pem` paths.
- Produces: `request_installation_token(config: BrokerConfig, transport: HttpTransport) -> str`.
- Produces: `serve_connection(connection: socket.socket, broker: TokenBroker) -> None`, accepting only `b"GET\\n"`.
- Produces: `read_token(socket_path: Path, timeout: float) -> str`.

- [ ] **Step 1: Write failing broker protocol tests**

```python
def test_broker_returns_one_installation_token_for_get_request() -> None:
    assert exchange(b"GET\\n") == b"installation-token\\n"


def test_broker_rejects_a_non_get_request_without_echoing_it() -> None:
    assert b"secret-input" not in exchange(b"secret-input\\n")
```

- [ ] **Step 2: Run the broker tests to verify they fail**

Run: `uv run --project tools/github_app_token_broker --group dev pytest tools/github_app_token_broker/tests/test_broker.py -v`

Expected: FAIL because the broker package does not exist.

- [ ] **Step 3: Implement the fixed-request broker**

Use `cryptography` only at the RS256 signing boundary. Base64url-encode fixed GitHub App JWT claims, request the fixed installation-token URL with `urllib.request`, bound every I/O size and timeout, and map failures to fixed messages.

- [ ] **Step 4: Run broker tests to verify they pass**

Run: `uv run --project tools/github_app_token_broker --group dev pytest tools/github_app_token_broker/tests/test_broker.py -v`

Expected: PASS.

- [ ] **Step 5: Write failing socket client validation tests**

```python
def test_client_returns_the_single_token_line_from_a_local_socket() -> None:
    assert read_token(socket_path, timeout=1) == "installation-token"


def test_client_rejects_a_multiline_socket_response() -> None:
    with pytest.raises(TokenClientError, match="cannot load GitHub App token"):
        read_token(socket_path, timeout=1)
```

- [ ] **Step 6: Run client tests to verify they fail**

Run: `uv run --project tools/github_app_token_broker --group dev pytest tools/github_app_token_broker/tests/test_client.py -v`

Expected: FAIL because the client is missing or does not validate the response.

- [ ] **Step 7: Implement `read_token(socket_path: Path, timeout: float) -> str`**

Connect with `socket.AF_UNIX`, send exactly `GET\n`, accept exactly one nonempty token line terminated by one newline, and raise `TokenClientError("cannot load GitHub App token")` for all transport and protocol failures.

- [ ] **Step 8: Run all broker tests and lint checks**

Run: `uv run --project tools/github_app_token_broker --group dev pytest tools/github_app_token_broker/tests && uv run --project tools/github_app_token_broker --group dev ruff format --check tools/github_app_token_broker/src tools/github_app_token_broker/tests && uv run --project tools/github_app_token_broker --group dev ruff check tools/github_app_token_broker/src tools/github_app_token_broker/tests`

Expected: PASS with no formatting or lint violations.

- [ ] **Step 9: Commit the broker package**

```bash
git add tools/github_app_token_broker
git commit -m "feat: add GitHub App token broker"
```

### Task 2: Add systemd deployment and install integration

**Files:**
- Create: `systemd/github-app-token.service`
- Create: `systemd/github-app-token.socket`
- Modify: `install.sh`
- Modify: `tests/install_test.sh`

**Interfaces:**
- Consumes: Task 1's broker module copied to `/usr/local/lib/ai-agent-home/` as root-owned source.
- Produces: `/run/github-app-token/token.sock`, mode `0660`, group `github-app-token`; an enabled `github-app-token.socket` system unit.

- [ ] **Step 1: Write failing installer behavior tests**

```bash
assert_contains "$output" "python3-cryptography" "dry-run installs system cryptography"
assert_contains "$output" "github-app-token.socket" "dry-run enables token socket"
assert_contains "$output" "/etc/ai-agent-home/github-app" "dry-run creates root-only App directory"
```

- [ ] **Step 2: Run installer test to verify it fails**

Run: `./tests/install_test.sh`

Expected: FAIL because the installer does not deploy the broker or socket.

- [ ] **Step 3: Add hardened service and socket units**

The socket creates the fixed path as `root:github-app-token` mode `0660`; the service invokes `/usr/bin/python3` on root-owned installed broker code. Restrict writes to its runtime location, keep only the network access GitHub HTTPS needs, and do not use `/home/takashi`, mise paths, or user-writable imports.

- [ ] **Step 4: Update `install.sh` for privileged deployment**

Install `python3-cryptography`, create the system group and add `takashi`, install source and unit files with root ownership and fixed modes, create the root-only configuration directory without migrating or printing secret bytes, daemon-reload systemd, and enable/start the socket. Keep mutations under `run_as_root`; dry-run only prints commands.

- [ ] **Step 5: Run installer tests to verify they pass**

Run: `./tests/install_test.sh`

Expected: PASS, including the new deployment assertions.

- [ ] **Step 6: Validate unit syntax**

Run: `systemd-analyze verify systemd/github-app-token.service systemd/github-app-token.socket`

Expected: PASS with no unit-file errors.

- [ ] **Step 7: Commit deployment integration**

```bash
git add systemd/github-app-token.service systemd/github-app-token.socket install.sh tests/install_test.sh
git commit -m "feat: install GitHub App token socket"
```

### Task 3: Preserve caller compatibility and document migration

**Files:**
- Modify: `bin/get-github-app-token.py`
- Modify: `bin/git-credential-helper`
- Modify: `README.md`
- Modify: `tools/github_app_token_broker/tests/test_client.py`
- Modify: `docs/HERDR-TASK-LIFECYCLE.md`

**Interfaces:**
- Consumes: Task 1's client and Task 2's socket.
- Produces: unchanged helper output: one installation token plus newline on success; generic stderr failure otherwise.

- [ ] **Step 1: Write a failing token-helper output-contract test**

```python
def test_cli_writes_only_the_socket_token_to_standard_output(capsys: pytest.CaptureFixture[str]) -> None:
    assert main() == 0
    assert capsys.readouterr().out == "test-installation-token\\n"
```

- [ ] **Step 2: Run focused token-helper test to verify it fails**

Run: `uv run --project tools/github_app_token_broker --group dev pytest tools/github_app_token_broker/tests/test_client.py -k cli_writes_only -v`

Expected: FAIL because the stable CLI wrapper is not backed by the socket client.

- [ ] **Step 3: Replace helper implementation and retain Git credential behavior**

Make `bin/get-github-app-token.py` a thin stable socket-client wrapper. Update the credential helper only as needed to propagate helper failure and never print an empty password. Preserve `GH_TOKEN` precedence in lifecycle code.

- [ ] **Step 4: Run caller checks**

Run: `uv run --project tools/github_app_token_broker --group dev pytest tools/github_app_token_broker/tests/test_client.py -v && uv run --project tools/herdr_task_lifecycle --group dev pytest tools/herdr_task_lifecycle/tests/commands/start/test_service.py -v && bash tests/herdr_task_lifecycle_test.sh`

Expected: PASS; existing explicit `GH_TOKEN` override tests remain green.

- [ ] **Step 5: Update operator documentation and implementation order**

Document root-only setup, migration, group refresh, socket status, token/Git verification without token display, and journal inspection. Remove #7 from the recommended order while keeping #8 and later issues ordered.

- [ ] **Step 6: Run documentation and regression verification**

Run: `./tests/install_test.sh && uv run --project tools/herdr_task_state --group dev pytest tools/herdr_task_state/tests && uv run --project tools/herdr_task_lifecycle --group dev pytest tools/herdr_task_lifecycle/tests && bash tests/herdr_task_lifecycle_test.sh && bash tests/herdr_runtime_test.sh && bash tests/herdr_agents_test.sh`

Expected: PASS.

- [ ] **Step 7: Commit compatibility and documentation**

```bash
git add bin/get-github-app-token.py bin/git-credential-helper README.md \
  tools/github_app_token_broker/tests/test_client.py \
  docs/HERDR-TASK-LIFECYCLE.md
git commit -m "feat: route GitHub authentication through token broker"
```

### Task 4: Verify the installed security boundary before pull request

**Files:**
- Modify: Task 1–3 files only if verification exposes a defect.

**Interfaces:**
- Consumes: installed service from Task 2 and clients from Task 3.
- Produces: evidence that Codex cannot read the key while authorized Git token retrieval works.

- [ ] **Step 1: Verify privileged-path access and service state without displaying secrets**

Run: `sudo -u takashi test ! -r /etc/ai-agent-home/github-app/private-key.pem && systemctl status github-app-token.socket --no-pager`

Expected: the read check succeeds and the socket is active or listening.

- [ ] **Step 2: Verify client and Git authentication without printing a token**

Run: `bin/get-github-app-token.py >/dev/null && git fetch --dry-run origin`

Expected: both commands exit zero; no token is printed or persisted.

- [ ] **Step 3: Inspect broker logs for secret disclosure**

Run: `journalctl -u github-app-token.service --no-pager -n 100`

Expected: no token, JWT, private-key bytes, or GitHub HTTP response body appears.

- [ ] **Step 4: Run complete automated verification**

Run: `git diff main...HEAD --check && ./tests/install_test.sh && uv run --project tools/github_app_token_broker --group dev pytest tools/github_app_token_broker/tests && uv run --project tools/herdr_task_state --group dev pytest tools/herdr_task_state/tests && uv run --project tools/herdr_task_lifecycle --group dev pytest tools/herdr_task_lifecycle/tests && bash tests/herdr_task_lifecycle_test.sh && bash tests/herdr_runtime_test.sh && bash tests/herdr_agents_test.sh`

Expected: all checks pass and the diff contains no secret material.

- [ ] **Step 5: Commit any verification fix and prepare the pull request**

If verification exposes a defect, add the exact Task 1–3 files that fix it,
commit with the conventional subject `fix: harden GitHub token broker`, then
run `git push`. If it exposes no defect, make no empty commit.

