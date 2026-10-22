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
| Codex CLI | Keep 0.155.1. | The version's [HTTP client source](https://github.com/openai/codex/blob/rust-v0.155.1/codex-rs/http-client/src/custom_ca.rs) loads native system roots by default; no eMudhra-specific fixed Codex version was identified. A custom `CODEX_CA_CERTIFICATE` or `SSL_CERT_FILE` bundle still needs separate inspection. |
| Herdr | Keep 0.8.2. | The [0.8.2 dependency manifest](https://github.com/herdrdev/herdr/blob/v0.8.2/Cargo.toml) and lockfile do not declare a TLS client or bundled CA dependency. No relevant fixed Herdr version was identified. |

These decisions concern the mise-managed executables on this host. They do not
update Ubuntu packages, Python project dependencies, other repositories' lock
files, or custom CA bundles. The operating system CA store remains a separate
maintenance responsibility.

## Apply and verify

From the feature worktree, install only the changed mise tools:

```bash
MISE_GLOBAL_CONFIG_FILE="$PWD/.config/mise/config.toml" mise install node python uv
MISE_GLOBAL_CONFIG_FILE="$PWD/.config/mise/config.toml" mise exec node -- node --version
MISE_GLOBAL_CONFIG_FILE="$PWD/.config/mise/config.toml" mise exec python -- python --version
MISE_GLOBAL_CONFIG_FILE="$PWD/.config/mise/config.toml" mise exec python -- python -m pip --version
MISE_GLOBAL_CONFIG_FILE="$PWD/.config/mise/config.toml" mise exec uv -- uv --version
MISE_GLOBAL_CONFIG_FILE="$PWD/.config/mise/config.toml" mise which node
MISE_GLOBAL_CONFIG_FILE="$PWD/.config/mise/config.toml" mise which python
MISE_GLOBAL_CONFIG_FILE="$PWD/.config/mise/config.toml" mise which uv
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
Blender's two bundled `cacert.pem` files also contained no affected root after
the refresh; its embedded Python reported certifi 2026.10.19 and pip's vendored
certifi 2026.10.19. Blender itself remained at 5.2.2.
