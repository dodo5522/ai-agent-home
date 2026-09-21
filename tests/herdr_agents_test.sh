#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"

test -f tools/herdr_agents/pyproject.toml
test -f tools/herdr_agents/uv.lock
test -x bin/herdr-agents
rg -q 'tools/herdr_agents' bin/herdr-agents bin/start-herdr-agents.sh
rg -q '^herdr-agents[[:space:]]*=' tools/herdr_agents/pyproject.toml
uv run --project tools/herdr_agents herdr-agents --help >/dev/null
