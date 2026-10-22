# eMudhra CA incident: mise-managed tools

Issue #67 was assessed on 2026-10-22. Mozilla removed `emSign ECC Root CA - G3`
from NSS 3.131.1 after the private keys of eight subordinate eMudhra CAs were
compromised. A client that still trusts this root may accept a forged TLS
certificate. See [Mozilla's incident report](https://blog.mozilla.org/security/2026/10/20/protecting-firefox-users-following-the-compromise-of-emudhra-intermediate-certificates/).

## Version decisions

| Tool | Decision | Evidence |
| --- | --- | --- |
| Node.js | Pin 24.22.1. | The [24.22.1 security release](https://nodejs.org/en/blog/release/v24.22.1) updates bundled roots to NSS 3.131.1 and blocks compromised public keys. |
| uv | Pin 0.13.4. | The [0.13.4 release](https://github.com/astral-sh/uv/releases/tag/0.13.4) updates `webpki-root-certs` to 1.0.10. Its [security advisory](https://github.com/astral-sh/uv/security/advisories/GHSA-hq85-5cpj-mr62) identifies 0.13.4 as the patched version. |
| Python | Pin 3.14.9. | The [3.14.9 security release](https://www.python.org/downloads/release/python-3149/) upgrades its embedded pip to 26.2.2 with certifi 2026.10.19 for this incident. The mise-installed 3.14.7 runtime had pip 26.2.1 and vendored certifi 2026.06.17, whose bundle contained the affected root. Standard-library `ssl` used `/etc/ssl/certs` on this host. |
| Blender | Keep 5.2.2 and refresh its bundled certifi and pip after mise installs it. | Its bundled Python used certifi 2025.04.26 and the affected root was present. The official [5.2.3 Linux archive](https://download.blender.org/release/Blender5.2/blender-5.2.3-linux-x64.tar.xz), available on 2026-10-22, contained a `certifi/cacert.pem` byte-identical to 5.2.2. The [certifi advisory](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2) identifies 2026.10.19 as patched. `bin/update-blender-certificates` uses pinned uv to install certifi 2026.10.19 and pip 26.2.2 into Blender's bundled Python. `install.sh` runs this command after `mise install`; run it separately after a direct Blender reinstall. |
| Claude Code | Pin 2.1.303 for the eMudhra CA response, superseding the user's 2.1.283 pin from the primary checkout's uncommitted config. | The [2.1.303 release notes](https://github.com/anthropics/claude-code/releases/tag/v2.1.303) only say “Bug fixes and reliability improvements.” The verified Anthropic Linux x64 binary adds a four-root certificate and public-key fingerprint deny list absent from the [2.1.283 binary](https://github.com/anthropics/claude-code/releases/tag/v2.1.283), and applies it when loading bundled, system, and `NODE_EXTRA_CA_CERTS` roots. See the binary comparison below. |
| Codex CLI | Carry forward the user's 0.160.1 pin from the primary checkout's uncommitted config. | This pin was not selected as a direct eMudhra CA remediation. No eMudhra-specific fixed Codex version was identified; custom `CODEX_CA_CERTIFICATE` or `SSL_CERT_FILE` bundles still need separate inspection. |
| Herdr | Keep 0.8.2. | The [0.8.2 dependency manifest](https://github.com/herdrdev/herdr/blob/v0.8.2/Cargo.toml) and lockfile do not declare a TLS client or bundled CA dependency. No relevant fixed Herdr version was identified. |

These decisions concern the mise-managed executables on this host. They do not
update Ubuntu packages, Python project dependencies, other repositories' lock
files, or custom CA bundles. The operating system CA store remains a separate
maintenance responsibility.

### Claude Code binary comparison

The official `claude-linux-x64.tar.gz` archives for 2.1.283 and 2.1.303 both
passed Anthropic's release `SHASUMS256.txt` check. The extracted executable
SHA-256 hashes were respectively
`1859583ce32920595c61ef868bee52e1b1594f7486db209935e01f1e5e804ae2` and
`375988f457756524234695cf2d8f64ace99c5f68682e47ea24862a843c191450`.
Neither binary simply removes the affected `emSign ECC Root CA - G3` certificate:
its DER bytes remain in both. Only 2.1.303 contains the following deny-list
certificate fingerprints (SHA-256), each paired in the binary with a public-key
fingerprint:

| Root | Certificate fingerprint |
| --- | --- |
| emSign Root CA - G1 | `40f6af0346a99aa1cd1d555a4e9cce62c7f9634603ee406615833dc8c8d00367` |
| emSign Root CA - C1 | `125609aa301da0a249b97a8239cb6a34216f44dcac9f3954b14292f2e8c8608f` |
| emSign ECC Root CA - G3 | `86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b` |
| emSign ECC Root CA - C3 | `bc4d809b15189d78db3e1d8cf4f9726a795da1643ca5f1358e1ddb0edc0d7eb3` |

The 2.1.303 code checks parsed roots against both fingerprint sets, removes
blocked roots from the assembled trust store, and processes the bundled, system,
and `NODE_EXTRA_CA_CERTS` sources through that filter. This is first-party
binary evidence of a targeted trust-store change, not a conclusion based on the
generic release notes. It does not establish that every TLS path or unrelated
custom CA setting uses this store.

## Apply and verify

From the feature worktree, install only the changed mise tools. The Codex CLI
pin carries forward the user's primary-checkout change; the Claude Code pin
supersedes the user's earlier value for this CA response:

```bash
MISE_GLOBAL_CONFIG_FILE="$PWD/.config/mise/config.toml" mise install node python uv
MISE_GLOBAL_CONFIG_FILE="$PWD/.config/mise/config.toml" mise install claude codex
MISE_GLOBAL_CONFIG_FILE="$PWD/.config/mise/config.toml" mise exec node -- node --version
MISE_GLOBAL_CONFIG_FILE="$PWD/.config/mise/config.toml" mise exec python -- python --version
MISE_GLOBAL_CONFIG_FILE="$PWD/.config/mise/config.toml" mise exec python -- python -m pip --version
MISE_GLOBAL_CONFIG_FILE="$PWD/.config/mise/config.toml" mise exec uv -- uv --version
MISE_GLOBAL_CONFIG_FILE="$PWD/.config/mise/config.toml" mise exec claude -- claude --version
MISE_GLOBAL_CONFIG_FILE="$PWD/.config/mise/config.toml" mise exec codex -- codex --version
MISE_GLOBAL_CONFIG_FILE="$PWD/.config/mise/config.toml" mise which node
MISE_GLOBAL_CONFIG_FILE="$PWD/.config/mise/config.toml" mise which python
MISE_GLOBAL_CONFIG_FILE="$PWD/.config/mise/config.toml" mise which uv
MISE_GLOBAL_CONFIG_FILE="$PWD/.config/mise/config.toml" mise which claude
MISE_GLOBAL_CONFIG_FILE="$PWD/.config/mise/config.toml" mise which codex
bin/update-blender-certificates
```

The expected versions are Node.js 24.22.1, Python 3.14.9 with pip 26.2.2,
and uv 0.13.4. Check the actual executable paths with `mise which`; a version
printed by an unrelated binary in `PATH` does not verify the mise installation.
This host also runs `bin/get-github-app-token.py` through the mise Python shim.
After changing the Python pin, restore its host-level dependency using the
same step as `install.sh`, then verify the import:

```bash
MISE_GLOBAL_CONFIG_FILE="$PWD/.config/mise/config.toml" mise exec python -- python -m pip install --upgrade 'PyJWT[crypto]'
MISE_GLOBAL_CONFIG_FILE="$PWD/.config/mise/config.toml" mise exec python -- python -c 'import jwt'
```

The Blender command changes only the Python environment inside the
mise-installed Blender tool. It pins both Blender's `certifi` package and its
pip copy of certifi, checks their versions, and rejects either bundle if it
still contains the affected root's SHA-256 fingerprint
`86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b`.
Run it again after `mise install blender` reinstalls or replaces Blender. Its
embedded Python path is specific to the pinned Blender 5.2.2 layout; update
the command when changing the Blender pin. The full
`install.sh` also invokes it, but that installer includes Ubuntu package
updates and is outside this Issue's scoped application.

Run these commands from the feature worktree so the primary checkout's
uncommitted mise configuration is left untouched. After the PR is merged, the
primary checkout can be synchronized through the normal Git workflow to select
the new pins.

On 2026-10-22, `mise install node python uv` completed in this worktree. `mise
which` selected `/home/takashi/.local/share/mise/installs/node/24.22.1/bin/node`,
`/home/takashi/.local/share/mise/installs/python/3.14.9/bin/python`, and
`/home/takashi/.local/share/mise/installs/uv/0.13.4/.mise-bins/uv`. The selected
executables reported `v24.22.1`, `Python 3.14.9` with `pip 26.2.2`, and
`uv 0.13.4`. The new pip reported vendored certifi 2026.10.19; parsing its
bundle and Node's built-in roots found no `emSign ECC Root CA - G3`.
The selected Claude Code and carried-forward Codex CLI pins resolved to
`/home/takashi/.local/share/mise/installs/claude/2.1.303/claude` and
`/home/takashi/.local/share/mise/installs/codex/0.160.1/bin/codex`, reporting
`2.1.303 (Claude Code)` and `codex-cli 0.160.1`.
Blender's two bundled `cacert.pem` files also contained no affected root after
the refresh; its embedded Python reported certifi 2026.10.19 and pip's vendored
certifi 2026.10.19. Blender itself remained at 5.2.2.
