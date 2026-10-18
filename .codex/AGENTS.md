# Herdr Issue task workflow (all repositories)

These instructions apply to Codex work in every repository on this VM. The
shared `herdr-task` command is `/home/takashi/bin/herdr-task` on `PATH`; do not
copy `.codex` or `tools/herdr_task_lifecycle` into another repository.

## Start an Issue task

- Create a unique task root directly below `/home/takashi/work/tasks/` and a
  regular `.codex-task-root` file directly inside it. Keep all task worktrees,
  clones, and agent-managed temporary files inside that root, for example in
  `worktree/`, `repo/`, and `tmp/`. Use another location only when the user
  explicitly requests it or a tool requires a system-managed temporary path.
- Create a dedicated feature worktree for the Issue below the marked task root.
  It must be a registered, non-primary Git worktree with an attached local
  branch. Follow that repository's branch and PR rules.
- From a Herdr-managed Pane, run `herdr-task start ISSUE --cwd WORKTREE` before
  creating implementation or investigation artifacts. `WORKTREE` must be the
  root of that feature worktree. The command registers the Issue's worktree,
  branch, Tab, Pane, and Agent in shared task state.
- Keep the task root, Tab, worktree, and task-state mapping while a PR is open
  or may still receive review updates. For work without a PR, wait for the
  user's explicit completion confirmation before cleanup.

## After a PR is merged

When the user reports a merge, switch the repository's primary checkout to
its target branch, pull the latest remote changes with fast-forward only, and
confirm that the local branch matches its remote-tracking branch. Then plan
cleanup from a checkout of **that same repository**: `cleanup` identifies the
task from the current directory's Git `origin`, even though the executable is
shared. Do not run cleanup from another repository's checkout.

1. Run `herdr-task cleanup ISSUE --plan --remove-untracked` and show the full,
   fresh JSON plan to the user. The plan must include Git-untracked,
   non-ignored paths in its approval scope. Check its task key, exact resolved
   task root, every target, and any `blocked` actions. Never clean up an
   unmanaged resource or another task's resource.
2. Obtain explicit human approval for that plan and exact task root. A plan
   alone, or a listed untracked path, does not authorize deletion.
3. Immediately after approval, run
   `herdr-task cleanup ISSUE --execute --remove-untracked --confirm-task-root EXACT_PATH`,
   substituting the exact `task_root` from the approved plan. Execution builds
   and validates a fresh plan; do not allow intervening state or resource
   changes. If the plan changes, show it and obtain fresh approval.
4. If cleanup stops partway through, keep the task-state mapping. Correct only
   the reported blocker, generate and show another fresh plan with
   `--remove-untracked`, obtain fresh approval, and retry guarded execution.

Existing worktrees outside task state, including blog-pet's `.worktrees/`, are
unmanaged. Inventory them separately; do not automatically adopt or remove
them. The detailed resource boundaries and retry procedure are in
`/home/takashi/docs/HERDR-TASK-LIFECYCLE.md`.

Codex reads this global file when a new session starts. Existing sessions do
not acquire the new instructions automatically.
