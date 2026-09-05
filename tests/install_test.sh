#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
INSTALLER="$REPO_ROOT/install.sh"
failures=0

fail() {
    printf 'not ok - %s\n' "$1"
    failures=$((failures + 1))
}

pass() {
    printf 'ok - %s\n' "$1"
}

assert_contains() {
    local haystack=$1
    local needle=$2
    local description=$3

    if [[ $haystack == *"$needle"* ]]; then
        pass "$description"
    else
        fail "$description (missing: $needle)"
    fi
}

test_dry_run_lists_every_install_phase() {
    local output

    if ! output=$(bash "$INSTALLER" --dry-run 2>&1); then
        fail "dry-run exits successfully"
        return
    fi
    pass "dry-run exits successfully"

    assert_contains "$output" "apt-get install" "dry-run includes Ubuntu packages"
    assert_contains "$output" "util-linux" "dry-run includes flock provider"
    assert_contains "$output" "tailscale.com/install.sh" "dry-run includes Tailscale"
    assert_contains "$output" "mise.run" "dry-run includes mise"
    assert_contains "$output" "mise install" "dry-run includes configured tools"
    assert_contains "$output" "PyJWT[crypto]" "dry-run includes Python dependencies"
}

test_help_documents_non_mutating_mode() {
    local output

    output=$(bash "$INSTALLER" --help 2>&1) || {
        fail "help exits successfully"
        return
    }
    pass "help exits successfully"
    assert_contains "$output" "--dry-run" "help documents dry-run"
}

test_unknown_option_fails() {
    local output

    if output=$(bash "$INSTALLER" --unknown 2>&1); then
        fail "unknown option returns non-zero"
        return
    fi
    pass "unknown option returns non-zero"
    assert_contains "$output" "unknown option" "unknown option explains the error"
}

test_runtime_paths_use_mise_shims() {
    local service
    local shebang
    local bootstrap

    service=$(cat "$REPO_ROOT/.config/systemd/user/herdr.service")
    shebang=$(head -n 1 "$REPO_ROOT/bin/github-app-token")
    bootstrap=$(cat "$REPO_ROOT/bin/start-herdr-agents.sh")

    assert_contains \
        "$service" \
        "/home/takashi/.local/share/mise/shims/herdr server" \
        "Herdr service uses the mise shim"
    if [[ $shebang == '#!/home/takashi/.local/share/mise/shims/python3' ]]; then
        pass "GitHub token helper uses the mise Python shim"
    else
        fail "GitHub token helper uses the mise Python shim"
    fi
    assert_contains \
        "$bootstrap" \
        '/home/takashi/.local/share/mise/shims/herdr' \
        "Herdr bootstrap uses the mise shim"
}

test_dry_run_lists_every_install_phase
test_help_documents_non_mutating_mode
test_unknown_option_fails
test_runtime_paths_use_mise_shims

if ((failures > 0)); then
    printf '%d test(s) failed\n' "$failures" >&2
    exit 1
fi
