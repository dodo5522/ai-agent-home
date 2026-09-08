#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
UV_BIN=${UV_BIN:-/home/takashi/.local/share/mise/shims/uv}

exec "$UV_BIN" run --project "$REPO_ROOT/tools/herdr_task_state" pytest -v
