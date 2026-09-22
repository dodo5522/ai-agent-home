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
rg -q 'herdr-task cleanup ISSUE --plan --remove-untracked' AGENTS.md
rg -q 'herdr-task cleanup 32 --plan --remove-untracked' docs/HERDR-TASK-LIFECYCLE.md
rg -q 'herdr-task cleanup ISSUE --plan --remove-untracked' docs/HERDR-TASK-LIFECYCLE.md
rg -q 'cleanup ISSUE --execute --remove-untracked --confirm-task-root' \
    docs/HERDR-TASK-LIFECYCLE.md
rg -q 'non-primary Git worktree' docs/HERDR-TASK-LIFECYCLE.md
rg -q 'worktree.*branch' docs/HERDR-TASK-LIFECYCLE.md
rg -q '#<issue-number> <short-title>' docs/HERDR-TASK-LIFECYCLE.md
rg -q 'herdr-agents reconcile' docs/HERDR-TASK-LIFECYCLE.md README.md
rg -q '\.config/herdr/agents\.toml' docs/HERDR-TASK-LIFECYCLE.md README.md
test -f .config/herdr/agents.toml.example
rg -q 'agents\.toml\.example' README.md docs/HERDR-TASK-LIFECYCLE.md
rg -q '^\.config/herdr/agents\.toml$' .gitignore
git check-ignore -q .config/herdr/agents.toml
rg -q 'herdr-agents.*path = "../herdr_agents"' tools/herdr_task_lifecycle/pyproject.toml
rg -q 'herdr-runtime.*path = "../herdr_runtime"' tools/herdr_task_lifecycle/pyproject.toml
! rg -q '^herdr-agents[[:space:]]*=' tools/herdr_task_lifecycle/pyproject.toml
rg -q 'exact.*Agent name|Agent name.*exact' docs/HERDR-TASK-LIFECYCLE.md
rg -q 'independently|per-Agent|Agent.*個別' docs/HERDR-TASK-LIFECYCLE.md
rg -q 'Issue implementer|implementer Agent' docs/HERDR-TASK-LIFECYCLE.md
rg -q '#44.*model|model.*#44' docs/HERDR-TASK-LIFECYCLE.md
rg -q '#10.*session|session.*#10' docs/HERDR-TASK-LIFECYCLE.md
rg -q 'create.*worktree.*then.*herdr-task start' AGENTS.md
test ! -e docs/HERDR-TASK-START.md
test ! -e bin/herdr-task-start
test ! -d tools/herdr_task_start
