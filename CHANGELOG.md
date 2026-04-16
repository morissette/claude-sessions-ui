# Changelog

All notable changes to this project will be documented in this file. Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [2.7.0] — 2026-04-15

### Fixed

- **TOOL/RESULT transcript blocks** — collapsed by default; click to expand to a 220 px scrollable area, drag bottom edge to resize. Chevron animates on toggle. Thicker left accent border (3 px) improves visual distinction (#26).
- **Session-id row** — pinned to the bottom of each session card instead of floating mid-card (#25).

---

## [2.6.0] — 2026-04-14

### Changed

- **Backend modularised** — `backend.py` split into a composable package: `app`, `parsing`, `database`, `fts`, `aggregation`, `process`, `ollama`, `metrics`, `memory`, `skills`, `detail`, `routes/`. No API surface change (#22).
- **Python 3.14** — runtime upgraded; `asyncio.get_event_loop()` deprecation warnings resolved.

---

## [2.5.0] — 2026-04-10

### Added

- **Batch operations** — multi-select sessions via checkbox, ZIP export of selected transcripts, CSV cost report, bulk Ollama summarise (#20).
- **Budget guardrails** — `BudgetBanner` displays a real-time breach alert when cumulative spend in the selected time range exceeds the configured threshold (#19).

---

## [2.4.0] — 2026-04-07

### Added

- **Cost trend charts** — daily cost breakdown bar chart with a configurable budget line overlay; accessible from StatsBar (#17).
- **Budget alert configuration** — threshold and currency unit editable directly in the UI.
- **Full-text session search** — `GET /api/search?q=` backed by SQLite FTS5; falls back to live JSONL grep for the `1d` range. Results panel with snippet highlighting (#16).
- **Session analytics panel** — second tab in the session detail overlay: per-turn cost curve (SVG), tool usage frequency bar, turn timeline (#14).
- **Memory explorer** — read-only file tree for `~/.claude/`; click to preview `.md`/`.txt`/`.json` files up to 50 KB. Path traversal blocked (#15).

---

## [2.3.0] — 2026-04-02

### Added

- **Project-level dashboard** — top-level view groups sessions by `project_path`; shows aggregate cost, token, and turn stats per project with drill-down to individual sessions (#13).
- **Per-model cost breakdown** — clicking the "Cost" tile in StatsBar opens a popover with a cost-per-model table for the selected time range (#10).
- **Unlimited history + custom date range** — calendar picker for arbitrary start/end dates beyond the 6 m preset maximum (#12).
- **Preference persistence** — active filter, sort order, and time range stored in `localStorage`; restored on reload (#11).

---

## [2.2.0] — 2026-04-15

### Changed

- **Slate design system** — complete light-theme overhaul replacing the deep purple-navy dark theme. New palette: `#f8f9fa` background, white surface, electric cyan (`#00d4ff`) as the single accent colour. Semantic stat colours: amber for cost, indigo for tokens, teal for cache reads, violet for turns, green for active/subagents.
- **Typography** — switched from Inter + JetBrains Mono to DM Sans (body) + DM Mono (values/code). Tighter letter-spacing and improved heading hierarchy throughout.
- **Header** — white surface with 1px bottom border; no backdrop blur or dark sticky bar.
- **Toolbar** — white background, active filter tab highlighted with solid cyan fill; active sort button uses cyan text + tinted background.
- **Session cards** — white surface, `border-top: 2px` accent stripe (green for active, neutral for idle). Branch tag uses cyan tint. Session ID row uses negative-margin full-bleed grey strip.
- **StatsBar tiles** — white tiles separated by 1px right borders; each stat type has its own semantic accent colour.
- **SessionDetail overlay** — lighter backdrop (`rgba(0,0,0,0.25)`), white panel. User bubbles get cyan tint; assistant bubbles get green left-accent border; tool/result blocks get amber/green accents respectively.
- **SavingsBanner** — green-tinted background on light surface instead of dark purple strip.

---

## [2.1.0] — 2026-04-10

### Added

- **Transcript export** — `GET /api/sessions/{id}/transcript` renders the full session as a downloadable Markdown file (`claude-session-{id}.md`). Accessible via the "↓ Transcript" button in the session detail overlay.
- **Export as skill** — `POST /api/sessions/{id}/export-skill` creates a Claude Code skill file from a session. Scope selector (global / local) and export button live in the session detail panel.
- **"view details →" hover hint on cards** — subtle affordance appears on card hover to signal clickability.

### Changed

- **Session detail overlay** — panel background lifted from near-black (`#0d0d24`) to readable slate-blue (`#1e1e3c`); backdrop blurs app content behind it. Messages show role labels ("You" / "Claude"), speaker-change dividers, and a smooth spring slide-in animation. Tool and result blocks have amber/green left-accent borders with pill-shaped type badges.
- **Summarize button** now calls `e.stopPropagation()` so clicking it no longer also opens the detail overlay.
- **Export as skill removed from session cards** — moved into the detail overlay to reduce card height and visual noise.

### Fixed

- **StatsBar Subagents tile had no accent colour** — CSS typo `.stat-sub_` (trailing underscore) corrected to `.stat-sub`; value now renders in green.
- **Subagents showed `—` when zero** — now renders `0` for consistency with other stat tiles.
- **`SessionCard.css` orphaned declarations** — missing `{` after `.card-title` left `font-size`, `color`, and `-webkit-line-clamp` detached from the rule; merged back in.

---

## [2.0.0] — 2026-04-05

### Added

- **SQLite historical storage** — sessions are persisted to `~/.claude/claude-sessions-ui.db`. On startup, all historical JSONL data is backfilled asynchronously. The DB is a derived cache; delete it and restart to rebuild from JSONL.
- **Time range filtering** — 7 time windows: `1h`, `1d`, `3d`, `1w`, `2w`, `1m`, `6m`. Short ranges (≤24h) use the live JSONL path; longer ranges query SQLite.
- **Range selector UI** — "Range" segmented control in the toolbar. Switching ranges reconnects the WebSocket with the new range parameter. The "Cost" tile in StatsBar updates its label dynamically to reflect the selected range.
- **`GET /api/db/status`** — diagnostic endpoint reporting total stored sessions, oldest/newest timestamps, and DB path.
- **Docker support** — multi-stage `Dockerfile` (Node 20 → Python 3.11), `docker-compose.yml` (mounts `~/.claude/` as a volume, connects to host Ollama via `OLLAMA_URL` env var), `.dockerignore`, and `docker.sh` convenience wrapper (`build`, `up`, `down`, `logs`).
- **`OLLAMA_URL` env var** — overrides the hardcoded `http://localhost:11434` default; required for Docker deployments pointing at host Ollama.

### Changed

- `GET /api/sessions` now accepts an optional `?time_range=` query parameter (default `1d`); response includes a `time_range` field.
- `WS /ws` now accepts an optional `?time_range=` query parameter (default `1d`); historical ranges (`3d`+) poll every 10 seconds instead of every 2 seconds.
- `compute_global_stats()` now accepts a `time_range_hours` parameter so the "cost" value reflects the selected window.
- `@app.on_event("startup")` replaced with the modern FastAPI `lifespan` context manager.

### Tests

- 17 new backend tests covering `init_db`, `upsert_sessions_to_db`, `get_sessions_from_db`, `get_sessions_for_range`, and `compute_global_stats` with time range. Total: 61 backend tests.
- Updated `StatsBar.test.jsx` to pass `timeRange` prop; 4 new label tests.
- New `App.test.jsx` covering the time range selector (all 7 buttons, default active state, click behaviour). Total frontend tests: 50.

---

## [1.1.0] — 2026-03-20

### Added

- **Savings analytics** — `SavingsBanner` component tracks estimated cost savings from PR-skip Ollama summaries and tool output truncation.
- **Prometheus metrics** — `GET /metrics` exports 10 gauges covering session counts, token totals, cache usage, and cost.
- **Subagent tracking** — backend identifies subagent activity within sessions; cards show coloured subagent chips with counts.
- **Session card summaries** — AI-generated Ollama summary text (Llama 3.2) shown inline on cards; "Summarize" button triggers on demand.

---

## [1.0.0] — 2026-03-01

### Added

- Initial release: real-time WebSocket dashboard reading `~/.claude/projects/` JSONL files.
- Session cards with token/cost display, model badge, active/idle status.
- StatsBar with aggregate totals: sessions, cost, output tokens, cache reads, turns, subagents.
- Filter tabs (All / Active / Today) and sort buttons (Recent / Cost / Turns).
- Ollama integration (Llama 3.2) for on-demand session summarisation; graceful degradation when unavailable.
- `GET /api/sessions` and `WS /ws` endpoints.
