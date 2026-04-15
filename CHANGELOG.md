# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added

- **Transcript export** — new `GET /api/sessions/{id}/transcript` endpoint renders the full session as a downloadable Markdown file (`claude-session-{id}.md`). Accessible via the "↓ Transcript" button in the session detail overlay.
- **Export as skill moved to detail overlay** — skill export controls (scope selector + export button) now live in the session detail panel, keeping cards clean and focused.
- **"view details →" hover hint on cards** — a subtle affordance appears on hover to signal that cards are clickable.

### Changed

- **Session detail overlay redesign** — panel background lifted from near-black (`#0d0d24`) to a readable slate-blue (`#1e1e3c`); backdrop blurs the app content behind it. Messages now show role labels ("You" / "Claude"), speaker-change dividers, and a smooth spring slide-in animation. Tool and result blocks have amber/green left-accent borders with pill-shaped type badges.
- **Summarize button** now calls `e.stopPropagation()` so clicking it no longer also opens the detail overlay.
- **Export as skill removed from session cards** — moved into the detail overlay to reduce card height and visual noise.

### Fixed

- **StatsBar Subagents tile had no accent color** — CSS typo `.stat-sub_` (trailing underscore) corrected to `.stat-sub`; the value now renders in green.
- **Subagents showed `—` when zero** — now renders `0` for consistency with other stat tiles.
- **`SessionCard.css` orphaned declarations** — missing `{` after `.card-title` left `font-size`, `color`, and `-webkit-line-clamp` detached from the rule; merged back in.

---

- **SQLite historical storage** — sessions are now persisted to `~/.claude/claude-sessions-ui.db`. On startup, all historical JSONL data is backfilled asynchronously. The DB is a derived cache; deleting it and restarting rebuilds from JSONL.
- **Time range filtering** — dashboard now supports 7 time windows: `1h`, `1d`, `3d`, `1w`, `2w`, `1m`, `6m`. Short ranges (≤24h) use the existing live JSONL path; longer ranges query SQLite.
- **Range selector UI** — new "Range" segmented control in the toolbar. Switching ranges reconnects the WebSocket with the new range parameter. The "Cost (today)" tile in `StatsBar` updates its label dynamically to reflect the selected range.
- **`GET /api/db/status`** — diagnostic endpoint reporting total stored sessions, oldest/newest timestamps, and DB path.
- **Docker support** — multi-stage `Dockerfile` (Node 20 → Python 3.11), `docker-compose.yml` (mounts `~/.claude/` as a volume, connects to host Ollama via `OLLAMA_URL` env var), `.dockerignore`, and `docker.sh` convenience wrapper (`build`, `up`, `down`, `logs`).
- **`OLLAMA_URL` env var** — overrides the hardcoded `http://localhost:11434` default; useful for Docker deployments.
- **Branch protection** — `main` now requires a pull request with 1 approving review before merge; force pushes and branch deletion are disabled.

### Changed

- `GET /api/sessions` now accepts an optional `?time_range=` query parameter (default `1d`) and includes a `time_range` field in the response.
- `WebSocket /ws` now accepts an optional `?time_range=` query parameter (default `1d`) and includes `time_range` in each broadcast. Historical ranges (`3d`+) poll every 10 seconds instead of every 2 seconds.
- `compute_global_stats()` now accepts a `time_range_hours` parameter; the "cost today" value reflects the selected range window rather than always being midnight-to-now.
- `@app.on_event("startup")` replaced with the modern FastAPI `lifespan` context manager.

### Tests

- 17 new backend tests covering `init_db`, `upsert_sessions_to_db`, `get_sessions_from_db`, `get_sessions_for_range`, and `compute_global_stats` with time range. Total: 61 backend tests.
- Updated `StatsBar.test.jsx` to pass `timeRange` prop and added 4 new label tests.
- New `App.test.jsx` covering the time range selector (renders all 7 buttons, default active state, click behavior).
- Total frontend tests: 50.
