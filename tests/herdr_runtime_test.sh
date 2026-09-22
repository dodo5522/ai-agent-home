#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"

test -f tools/herdr_runtime/pyproject.toml
test -f tools/herdr_runtime/uv.lock
! rg -q '^\[project\.scripts\]' tools/herdr_runtime/pyproject.toml
uv run --project tools/herdr_runtime python -c 'import herdr_runtime'
