#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
INSTALLER="$REPO_ROOT/install.sh"
HERDR_SKILL="$REPO_ROOT/.codex/skills/herdr/SKILL.md"
HERDR_SKILL_PROVENANCE="$REPO_ROOT/.codex/skills/herdr/UPSTREAM.md"
HERDR_SKILL_DOC="$REPO_ROOT/docs/HERDR-SKILL.md"
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
    shebang=$(head -n 1 "$REPO_ROOT/bin/github-app-token.py")
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

test_herdr_skill_is_installed_with_safety_contract() {
    local skill

    if [[ ! -f $HERDR_SKILL ]]; then
        fail "Herdr Skill is installed for Codex"
        return
    fi
    pass "Herdr Skill is installed for Codex"

    skill=$(<"$HERDR_SKILL")
    assert_contains "$skill" 'Requires HERDR_ENV=1.' "Skill requires a Herdr-managed pane"
    assert_contains "$skill" 'herdr agent list' "Skill documents agent discovery"
    assert_contains "$skill" 'herdr agent start' "Skill documents agent startup"
    assert_contains "$skill" 'herdr agent prompt' "Skill documents agent prompting"
    assert_contains "$skill" 'herdr agent wait' "Skill documents agent waiting"
    assert_contains "$skill" 'herdr agent get' "Skill documents agent state inspection"
    assert_contains "$skill" 'herdr agent read' "Skill documents agent output retrieval"
    assert_contains "$skill" '.result.pane.pane_id' "Skill parses pane IDs from JSON"
    assert_contains "$skill" '--current' "Skill supports caller-relative pane targeting"
    assert_contains "$skill" '--no-focus' "Skill preserves focus for background work"
    assert_contains "$skill" 'unique live agent name' "Skill requires unique Agent names"
    assert_contains "$skill" '`idle`' "Skill defines idle state"
    assert_contains "$skill" '`working`' "Skill defines working state"
    assert_contains "$skill" '`blocked`' "Skill defines blocked state"
    assert_contains "$skill" '`done`' "Skill defines done state"
    assert_contains "$skill" '`unknown`' "Skill defines unknown state"
    assert_contains "$skill" 'Do not rely on another client' "Skill avoids focused-pane targeting"
    assert_contains "$skill" 'ask the user before answering it' "Skill leaves blocked decisions to the user"
}

test_herdr_skill_records_reproducible_upstream() {
    local actual_checksum
    local pinned_commit
    local provenance
    local recorded_checksum

    if [[ ! -f $HERDR_SKILL_PROVENANCE ]]; then
        fail "Herdr Skill records upstream provenance"
        return
    fi
    pass "Herdr Skill records upstream provenance"

    provenance=$(<"$HERDR_SKILL_PROVENANCE")
    pinned_commit=$(sed -n 's/^- Commit: `\([0-9a-f]\{40\}\)`$/\1/p' \
        "$HERDR_SKILL_PROVENANCE")
    if [[ -n $pinned_commit ]]; then
        pass "provenance pins an immutable upstream revision"
    else
        fail "provenance pins an immutable upstream revision"
    fi

    recorded_checksum=$(sed -n 's/^- SHA-256: `\([0-9a-f]\{64\}\)`$/\1/p' \
        "$HERDR_SKILL_PROVENANCE")
    actual_checksum=$(sha256sum "$HERDR_SKILL")
    actual_checksum=${actual_checksum%% *}
    if [[ -n $recorded_checksum && $recorded_checksum == "$actual_checksum" ]]; then
        pass "provenance checksum matches the vendored Skill"
    else
        fail "provenance checksum matches the vendored Skill"
    fi
}

test_herdr_skill_setup_and_update_are_documented() {
    local documentation

    if [[ ! -f $HERDR_SKILL_DOC ]]; then
        fail "Herdr Skill setup document exists"
        return
    fi
    pass "Herdr Skill setup document exists"

    documentation=$(<"$HERDR_SKILL_DOC")
    assert_contains "$documentation" '.codex/skills/herdr/SKILL.md' "setup documents Skill placement"
    assert_contains "$documentation" 'HERDR_ENV=1' "setup documents the runtime requirement"
    assert_contains "$documentation" 'upstream' "setup documents upstream updates"
    assert_contains "$documentation" 'mktemp' "setup uses a unique update-check path"
    assert_contains "$documentation" 'trap' "setup cleans up the update-check file"
    assert_contains "$documentation" 'commit' "setup documents immutable upstream revisions"
    assert_contains "$documentation" '固有の Agent 名' "setup documents unique Agent targeting"
    assert_contains "$documentation" 'JSON 応答' "setup documents JSON-derived IDs"
    assert_contains "$documentation" '`--current`' "setup documents current-pane targeting"
    assert_contains "$documentation" '`--no-focus`' "setup documents background focus preservation"
    assert_contains "$documentation" '承認や回答を自動送信しない' \
        "setup prohibits automatic blocked-state answers"
    assert_contains "$documentation" '`idle`' "setup documents idle handling"
    assert_contains "$documentation" '`working`' "setup documents working handling"
    assert_contains "$documentation" '`blocked`' "setup documents blocked handling"
    assert_contains "$documentation" '`done`' "setup documents done handling"
    assert_contains "$documentation" '`unknown`' "setup documents unknown handling"
    assert_contains "$documentation" '#9' "setup documents related Agent management work"
    assert_contains "$documentation" '#11' "setup documents related worktree work"
    assert_contains "$documentation" '#12' "setup documents related reviewer work"
    assert_contains "$documentation" '#17' "setup documents related notification work"
}

test_dry_run_lists_every_install_phase
test_help_documents_non_mutating_mode
test_unknown_option_fails
test_runtime_paths_use_mise_shims
test_herdr_skill_is_installed_with_safety_contract
test_herdr_skill_records_reproducible_upstream
test_herdr_skill_setup_and_update_are_documented

if ((failures > 0)); then
    printf '%d test(s) failed\n' "$failures" >&2
    exit 1
fi
