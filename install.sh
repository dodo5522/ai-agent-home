#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
MISE_CONFIG_FILE="$REPO_ROOT/.config/mise/config.toml"
DRY_RUN=false

usage() {
    cat <<'EOF'
Usage: ./install.sh [--dry-run] [--help]

Install the Ubuntu packages, Tailscale, mise-managed tools, and Python
packages required by this home-directory template.

Options:
  --dry-run  Print the installation steps without changing the system.
  --help     Show this help message.
EOF
}

log() {
    printf 'install: %s\n' "$*"
}

show_command() {
    printf '+ '
    printf '%q ' "$@"
    printf '\n'
}

run() {
    if [[ $DRY_RUN == true ]]; then
        show_command "$@"
    else
        "$@"
    fi
}

run_as_root() {
    if ((EUID == 0)); then
        run "$@"
    else
        run sudo "$@"
    fi
}

download_and_run() {
    local url=$1
    local destination=$2
    shift 2

    run curl -fsSL "$url" -o "$destination"
    run "$@" "$destination"
}

for argument in "$@"; do
    case "$argument" in
        --dry-run)
            DRY_RUN=true
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            printf 'install: unknown option: %s\n' "$argument" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ ! -f $MISE_CONFIG_FILE ]]; then
    printf 'install: mise config not found: %s\n' "$MISE_CONFIG_FILE" >&2
    exit 1
fi

if [[ $DRY_RUN != true ]]; then
    if [[ ! -r /etc/os-release ]]; then
        printf 'install: cannot identify the operating system\n' >&2
        exit 1
    fi

    if ((EUID == 0)); then
        printf 'install: run this installer as the login user, not as root\n' >&2
        exit 1
    fi

    if [[ $HOME != /home/takashi || $REPO_ROOT != /home/takashi ]]; then
        printf '%s\n' \
            'install: this template must be installed as takashi at /home/takashi' \
            >&2
        exit 1
    fi

    # shellcheck disable=SC1091
    source /etc/os-release
    if [[ ${ID:-} != ubuntu ]]; then
        printf 'install: unsupported operating system: %s (Ubuntu required)\n' \
            "${ID:-unknown}" >&2
        exit 1
    fi

    if ! command -v sudo >/dev/null 2>&1; then
        printf 'install: sudo is required\n' >&2
        exit 1
    fi
fi

temporary_directory="${TMPDIR:-/tmp}/ai-agent-home-install.$$"
if [[ $DRY_RUN != true ]]; then
    temporary_directory=$(mktemp -d)
    trap 'rm -rf "$temporary_directory"' EXIT
fi

log "installing Ubuntu packages"
run_as_root apt-get update
run_as_root apt-get install -y --no-install-recommends \
    build-essential ca-certificates curl git jq gh util-linux

if [[ $DRY_RUN == true ]] || ! command -v tailscale >/dev/null 2>&1; then
    log "installing Tailscale"
    download_and_run \
        https://tailscale.com/install.sh \
        "$temporary_directory/install-tailscale.sh" \
        sh
else
    log "Tailscale is already installed; skipping"
fi

mise_bin=$(command -v mise 2>/dev/null || true)
if [[ $DRY_RUN == true ]] || [[ -z $mise_bin ]]; then
    log "installing mise"
    download_and_run \
        https://mise.run \
        "$temporary_directory/install-mise.sh" \
        sh
    mise_bin="$HOME/.local/bin/mise"
else
    log "mise is already installed; skipping"
fi

if [[ $DRY_RUN != true && ! -x $mise_bin ]]; then
    printf 'install: mise executable not found after installation: %s\n' \
        "$mise_bin" >&2
    exit 1
fi

log "installing tools from $MISE_CONFIG_FILE"
if [[ $DRY_RUN == true ]]; then
    printf '+ MISE_GLOBAL_CONFIG_FILE=%q %q install\n' \
        "$MISE_CONFIG_FILE" "${mise_bin:-$HOME/.local/bin/mise}"
else
    MISE_GLOBAL_CONFIG_FILE="$MISE_CONFIG_FILE" "$mise_bin" install
fi

log "installing Python packages"
if [[ $DRY_RUN == true ]]; then
    printf "+ MISE_GLOBAL_CONFIG_FILE=%q %q exec python -- python -m pip install --upgrade '%s'\n" \
        "$MISE_CONFIG_FILE" "${mise_bin:-$HOME/.local/bin/mise}" 'PyJWT[crypto]'
else
    MISE_GLOBAL_CONFIG_FILE="$MISE_CONFIG_FILE" "$mise_bin" exec python -- \
        python -m pip install --upgrade 'PyJWT[crypto]'
fi

log "verifying installed dependencies"
run jq --version
run gh --version
run flock --version
run tailscale version
if [[ $DRY_RUN == true ]]; then
    printf '+ MISE_GLOBAL_CONFIG_FILE=%q %q current\n' "$MISE_CONFIG_FILE" "$mise_bin"
    printf '+ MISE_GLOBAL_CONFIG_FILE=%q %q exec python -- python -c %q\n' \
        "$MISE_CONFIG_FILE" "$mise_bin" 'import jwt'
else
    MISE_GLOBAL_CONFIG_FILE="$MISE_CONFIG_FILE" "$mise_bin" current
    MISE_GLOBAL_CONFIG_FILE="$MISE_CONFIG_FILE" "$mise_bin" exec python -- \
        python -c 'import jwt'
fi

log "dependency installation completed"
