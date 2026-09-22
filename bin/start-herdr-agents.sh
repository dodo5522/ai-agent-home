#!/usr/bin/env bash
set -euo pipefail

HERDR_BIN=${HERDR_BIN:-/home/takashi/.local/share/mise/shims/herdr}
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
HERDR_AGENT_CONFIG=${HERDR_AGENT_CONFIG:-${WORKSPACE_CWD:-/home/takashi}/.config/herdr/agents.toml}
LOCK_FILE=${LOCK_FILE:-${XDG_RUNTIME_DIR:-/tmp}/herdr-agents.lock}
SERVER_WAIT_ATTEMPTS=${SERVER_WAIT_ATTEMPTS:-60}
SERVER_WAIT_INTERVAL=${SERVER_WAIT_INTERVAL:-2}
WORKSPACE_CWD=${WORKSPACE_CWD:-/home/takashi}

log() {
    printf '%s\n' "herdr-agents: $*"
}

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    log "another bootstrap is already running; exiting"
    exit 0
fi

server_ready=false
for ((attempt = 1; attempt <= SERVER_WAIT_ATTEMPTS; attempt++)); do
    if status_json=$($HERDR_BIN status --json 2>/dev/null) &&
       jq -e '.server.running == true and .server.compatible == true' \
          >/dev/null 2>&1 <<<"$status_json"; then
        server_ready=true
        break
    fi
    sleep "$SERVER_WAIT_INTERVAL"
done

if [[ $server_ready != true ]]; then
    log "Herdr server did not become ready"
    exit 1
fi

log "reconciling configured Herdr Agents from $HERDR_AGENT_CONFIG"
HERDR_BIN="$HERDR_BIN" "$SCRIPT_DIR/herdr-agents" reconcile --config "$HERDR_AGENT_CONFIG"
