#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"

rg -q 'herdr-task start' docs/HERDR-TASK-LIFECYCLE.md
rg -q 'HERDR-TASK-LIFECYCLE.md' README.md AGENTS.md docs/HERDR-TASK-STATE.md
rg -Uq 'repository-wide managed resource shared by tasks in the same[[:space:]]+repository' \
    docs/HERDR-TASK-LIFECYCLE.md
rg -q 'does not bind execution to the previously displayed plan' \
    docs/HERDR-TASK-LIFECYCLE.md
rg -q 'herdr-task cleanup ISSUE --plan' AGENTS.md
test ! -e docs/HERDR-TASK-START.md
test ! -e bin/herdr-task-start
test ! -d tools/herdr_task_start
