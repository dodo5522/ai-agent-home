#!/usr/bin/env bash
set -euo pipefail

HERDR_BIN=${HERDR_BIN:-/home/takashi/.local/share/mise/shims/herdr}
CODEX_SESSION_INDEX=${CODEX_SESSION_INDEX:-${HOME}/.codex/session_index.jsonl}
LOCK_FILE=${LOCK_FILE:-${XDG_RUNTIME_DIR:-/tmp}/herdr-agents.lock}
SERVER_WAIT_ATTEMPTS=${SERVER_WAIT_ATTEMPTS:-60}
SERVER_WAIT_INTERVAL=${SERVER_WAIT_INTERVAL:-2}
AGENT_NAME=${AGENT_NAME:-codex-main}
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

agent_json=$($HERDR_BIN agent list)
if jq -e '.result.agents[]? | select(.agent == "codex")' \
      >/dev/null 2>&1 <<<"$agent_json"; then
    log "a live Codex agent already exists; nothing to do"
    exit 0
fi

pane_id=""
workspace_json=$($HERDR_BIN workspace list)
while IFS= read -r workspace_id; do
    [[ -n $workspace_id ]] || continue
    pane_json=$($HERDR_BIN pane list --workspace "$workspace_id")
    while IFS= read -r candidate_id; do
        [[ -n $candidate_id ]] || continue
        process_json=$($HERDR_BIN pane process-info --pane "$candidate_id")
        if jq -e '.result.process_info.foreground_processes | length == 0' \
              >/dev/null 2>&1 <<<"$process_json"; then
            pane_id=$candidate_id
            break 2
        fi
    done < <(jq -r '.result.panes[]? | select(.agent == null) | .pane_id' \
                    <<<"$pane_json")
done < <(jq -r '.result.workspaces[]?.workspace_id' <<<"$workspace_json")

if [[ -z $pane_id ]]; then
    create_json=$($HERDR_BIN workspace create --cwd "$WORKSPACE_CWD" --no-focus)
    pane_id=$(jq -r '.result.root_pane.pane_id // empty' <<<"$create_json")
fi

if [[ -z $pane_id ]]; then
    log "could not obtain an available pane"
    exit 1
fi

has_saved_session=false
if [[ -s $CODEX_SESSION_INDEX ]] &&
   jq -s -e 'any(.[]; (.id? // "") != "")' "$CODEX_SESSION_INDEX" \
      >/dev/null 2>&1; then
    has_saved_session=true
fi

if [[ $has_saved_session == true ]]; then
    log "resuming the most recent saved Codex session in pane $pane_id"
    if $HERDR_BIN agent start "$AGENT_NAME" --kind codex --pane "$pane_id" \
         -- resume --last --all; then
        exit 0
    fi

    # A startup timeout can occur after Codex has actually appeared. Re-check
    # before attempting the fresh-session fallback.
    agent_json=$($HERDR_BIN agent list)
    if jq -e '.result.agents[]? | select(.agent == "codex")' \
          >/dev/null 2>&1 <<<"$agent_json"; then
        log "Codex became visible after the resume command returned"
        exit 0
    fi
    log "saved-session resume failed; starting a new Codex session"
fi

$HERDR_BIN agent start "$AGENT_NAME" --kind codex --pane "$pane_id"
