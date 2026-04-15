# User Feedback Patterns & Preferred Approaches

## Git & PR Workflow

### All features go through PRs — branch protection on main
Branch protection was set up in session `37f1dfab`. Direct pushes to `main` are blocked. Every feature must be on its own branch with a PR.

### `--auto` is injected into every `gh pr merge` call
A `PreToolUse` hook in `.claude/settings.json` rewrites `gh pr merge` to `gh pr merge --auto` for all PRs on this repo. Never manually add `--auto` — it's already there.

### Parallel agents via worktrees for multi-feature work
When executing multiple feature plans simultaneously, each feature gets an isolated worktree (in `.claude/worktrees/`), a dedicated branch, and a full spec. Parallel worktree agents are the preferred approach for Wave-style feature batches.

### Sequential merges after rebase — not parallel
When multiple feature PRs are ready, merge them one at a time. After each merge lands on main, rebase the remaining branches before the next merge. Parallel merges create conflicts that are harder to untangle.

### Address Copilot comments before merging
Use `/watch-copilot` or `/resolve-copilot` to address all unresolved Copilot review threads and resolve them in GitHub before merging a PR. Copilot re-reviews after each push — check `requested_reviewers` to confirm Copilot has finished before treating the thread list as complete.

### Copilot API re-request returns 422 on this repo
`morissette/claude-sessions-ui` is a personal repo without Copilot as a collaborator — the `POST /requested_reviewers` API call returns 422. Re-request Copilot review manually from the GitHub UI after each push.

### Drop contaminating commits via cherry-pick, not rebase -i
When an agent accidentally includes commits from another feature branch (e.g., Feature 3's analytics commit ending up on Feature 7's branch), fix it by cherry-picking the intended commits onto a fresh branch from main, then force-pushing. Don't try to surgically remove commits with interactive rebase on a dirty branch.

### CI must pass before merge (never `--no-verify`)
All four checks must be green: `ruff check backend.py`, `pytest tests/ -v`, `npm run lint`, `npm test`. Never skip hooks or bypass CI.

## Code Style

### Keep backend.py as one file
Don't split into modules. The single-file pattern is intentional and preferred. Sections use `# ─── Section ───` dividers.

### Run ruff + pytest before suggesting a commit
Always verify `ruff check backend.py` and `pytest tests/ -v` pass locally. Ruff failures and ESLint errors block CI.

### New Claude models need both a pricing entry and a test
When adding a model to `MODEL_PRICING`, always add a corresponding test in `tests/test_backend.py`. Both are required.

## Feature Development

### Plan first, then implement
For significant features, write a plan doc to `docs/plans/` first (or open a plan PR like #9). Then implement from the spec. `/plan` mode is used before implementation sessions.

### frontend/dist should never be committed
`frontend/dist/` is in `.gitignore` and must stay untracked. If dist files end up tracked, use `git rm --cached` to untrack them (done in PR #7 session).

### Use `key` prop to reset component state instead of `useEffect` setState
When a component needs to reset all state on prop change (e.g., `SessionDetail` resetting when `sessionId` changes), use `key={sessionId}` on the component instead of calling multiple `setState` calls inside a `useEffect`. Avoids react-hooks/exhaustive-deps lint violations.

## Infrastructure

### launchd service always wins port 8765
When the app isn't showing merged changes, check whether `com.marie.claude-sessions-ui.plist` (launchd) is running a stale build. Reload the service after rebuilding `frontend/dist/`, or rebuild dist locally before reloading.

### SQLite DB is safe to delete
If the DB is corrupted (wrong magic bytes or schema mismatch), just delete `~/.claude/claude-sessions-ui.db` and restart. The startup backfill will rebuild it from JSONL.

### Grafana 12 requires `"range": true` on provisioned timeseries panels
Without `"range": true` in the datasource target, provisioned dashboards default to instant queries — panels render as blank (single point, no line). Always add `"range": true` to timeseries panel targets in provisioned Grafana 12 dashboards.
