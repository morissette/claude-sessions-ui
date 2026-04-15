# Roadmap: AI Assistant Dashboard

## Vision

Claude Sessions UI started as a cost tracker. The AI Assistant Dashboard is where it ends up: the single pane of glass for everything happening between you and Claude Code. It answers three questions every power user asks daily: _What did I spend? What did Claude actually do? What does Claude know about my projects?_

It stays local-first, single-user, zero-config — reads what Claude writes to disk and never phones home. Every feature either saves you money, saves you time, or shows you something you couldn't see before.

---

## Principles

- **Local-first, zero-config** — no accounts, no cloud sync, no `.env` required
- **Reads, never writes** — the dashboard observes Claude's state; it does not mutate it (except opt-in actions like skill export or batch summarize)
- **Degrades gracefully** — every feature that touches Ollama works without it
- **SQLite is a cache** — every table can be deleted and rebuilt from JSONL; SQLite is never the source of truth
- **No dependency creep** — no TypeScript, no state management library, no UI component library, no heavy charting library

---

## Current Features (Baseline)

Everything shipped today that new features build on:

| # | Feature | Description |
|---|---------|-------------|
| 1 | Real-time WebSocket feed | Streams session list + stats every 2s (live) or 10s (historical); auto-reconnects |
| 2 | JSONL session discovery + parsing | Scans `~/.claude/projects/`; extracts tokens, costs, model, branch, turns, subagents; mtime-cached |
| 3 | Process discovery | Detects active Claude PIDs via psutil; marks sessions live |
| 4 | Cost estimation | MODEL_PRICING table for 8 model variants; per-session + aggregate USD cost |
| 5 | Compact potential advisor | Estimates /compact savings; badge on cards when > $0.005 |
| 6 | Time range filtering | 1h / 1d / 3d / 1w / 2w / 1m / 6m; short ranges from JSONL, long from SQLite |
| 7 | SQLite historical store | Startup backfill + live upsert; WAL mode; enables historical queries |
| 8 | Session filtering + sorting | All / Active / Today tabs; sort by Recent / Cost / Turns |
| 9 | Session cards | Status dot, model badge, token bar, subagent chips, cost row, "view details" hint |
| 10 | Session detail overlay | Paginated message viewer (200/page); tool blocks, thinking blocks, Escape to close |
| 11 | Transcript export | Download full session as Markdown |
| 12 | Export as skill | Create a Claude Code skill file from a session (global or local scope) |
| 13 | Ollama summarization | llama3.2:3b generates short session summaries cached to disk |
| 14 | Aggregate stats bar | Sessions, Cost, Output tokens, Cache reads, Turns, Subagents tiles |
| 15 | Savings banner | Ollama savings + truncation hook savings in USD; per-tool breakdown |
| 16 | Prometheus metrics | `/metrics` with 10 gauges: sessions, tokens, cost, turns, subagents |
| 17 | Docker deployment | Multi-stage Dockerfile + docker-compose; Ollama URL via env var |
| 18 | Subagent tracking | Type chips from `subagents/*.meta.json`; global subagent total in stats bar |

---

## Phase 1 — Depth (Q2 2026)

_Build on the existing JSONL parser and SQLite store. No new infrastructure required. Highest ratio of user value to implementation effort._

### 1. Full-Text Session Search

> Search all session transcripts by keyword; results highlight matching messages and link directly to that message in context.

**User benefit:** Find sessions from weeks or months ago by content — no more grepping JSONL files on disk or scrolling through session cards trying to remember when you solved a particular error.

**Effort:** M

**Technical notes:** Add a FTS5 virtual table in SQLite (built into Python's `sqlite3` module, no new dependencies). New `GET /api/search?q=&time_range=` endpoint iterates the index for historical ranges or greps JSONL line-by-line (in a thread pool) for live ranges. Frontend: search input in the toolbar; a results view replaces the session grid when a query is active, showing session title, matched message snippet with highlighted terms, timestamp, and a click-to-open that jumps to that offset in the detail overlay. Extend `_startup_backfill` to also populate the FTS index.

---

### 2. Unlimited Session History + Custom Date Range

> Browse sessions from any date with a date-range picker and an "All time" option; removes the 6-month ceiling entirely.

**User benefit:** Long-term Claude Code users lose nothing to an arbitrary time cliff. Find that session from nine months ago without exporting or searching the filesystem.

**Effort:** S

**Technical notes:** The SQLite store already contains all backfilled sessions with no upper date limit — the 6-month ceiling is only in the `TIME_RANGE_HOURS` dict. Add `"all": None` to that dict. Add a `"custom"` entry that accepts `start`/`end` ISO timestamps as query params on both the WebSocket and `/api/sessions`. On the frontend, add an "All" button to `TIME_RANGES` and a date-range picker (two native `<input type="date">` fields) that appears when "Custom" is selected. The SQLite index on `last_active` already supports range queries efficiently.

---

### 3. Session Analytics Panel

> A per-session "Analytics" tab alongside "Messages" showing: turn-by-turn token timeline, cumulative cost curve, tool usage frequency breakdown, thinking-to-output ratio, and a turn duration chart.

**User benefit:** The session detail is currently a message viewer. This turns it into a diagnostic tool. See exactly which turn blew up the token count, which tools Claude leaned on hardest, and whether extended thinking is dominating your spend.

**Effort:** L

**Technical notes:** New `GET /api/sessions/{id}/analytics` endpoint does a full JSONL parse and returns:
- `token_timeline` — `[{turn, input_tokens, output_tokens, cache_read_tokens, cumulative_cost_usd}]`
- `tool_frequency` — `{tool_name: count}` dict
- `thinking_stats` — `{total_thinking_chars, total_output_chars, ratio, turns_with_thinking}`
- `turn_durations` — `[{turn, duration_seconds}]` (timestamp gaps between user messages)
- `model_switches` — `[{turn, from_model, to_model}]` if model changed mid-session

Frontend: tabbed sub-navigation inside SessionDetail ("Messages" / "Analytics"). Charts rendered with [uPlot](https://github.com/leeoniya/uPlot) (~35 KB) or raw SVG — no Chart.js or Recharts. Token timeline = stacked area chart; tool frequency = horizontal bar chart; cost curve = line chart.

---

### 4. Project-Level Dashboard

> Group sessions by project and show per-project aggregate stats: total cost, session count, total tokens, most-used model, and date range of activity.

**User benefit:** A developer running Claude Code across 8–10 repos wants to know: "How much am I spending on the infrastructure repo vs. the frontend repo?" and "Which project has had the most activity this week?" The current flat session list does not answer this.

**Effort:** M

**Technical notes:** New `GET /api/projects` endpoint queries SQLite `GROUP BY project_path` and returns `[{project_path, project_name, session_count, total_cost_usd, total_tokens, models_used, first_session, last_session}]`. Frontend: top-level toggle "Sessions" vs. "Projects" in the toolbar. The Projects view is a card grid where each project card shows aggregate stats and is clickable to filter the session list to that project. Add `?project=` filter param to the WebSocket. No schema changes needed — `project_path` is already stored.

---

## Phase 2 — Intelligence (Q3 2026)

_New data sources and new computation. The dashboard stops being a session viewer and becomes an operational intelligence tool._

### 5. Cost Trend Charts + Budget Alerts

> A daily/weekly cost chart broken down by model with a configurable budget threshold rendered as a dashed line; when daily spend exceeds the threshold, the StatsBar cost tile turns red and a warning banner appears.

**User benefit:** The current StatsBar shows a single number with no sense of trajectory. A trend chart reveals whether costs are growing week-over-week. A budget threshold turns passive monitoring into active alerting — you know before the month ends, not after.

**Effort:** L

**Technical notes:** New `daily_costs(date TEXT, model TEXT, cost_usd REAL, tokens INTEGER, session_count INTEGER, PRIMARY KEY(date, model))` SQLite table. `GET /api/costs/daily?days=30` returns the time series. Collapsible "Trends" section between StatsBar and toolbar. Stacked bar chart (one bar per day, segments by model) rendered with uPlot or SVG. Budget threshold stored in `~/.claude/claude-sessions-ui-config.json` (not localStorage — persists across browser cache clears). Extend `_startup_backfill` to populate `daily_costs`; daily upsert also updates the current day's row.

---

### 6. Memory Explorer

> A dedicated view for browsing and reading Claude's entire memory system: global and per-project `memory/` files, CLAUDE.md files, skills, commands, agents, and hooks — all in one tree-structured panel.

**User benefit:** Claude Code's memory system is a collection of Markdown files scattered across `~/.claude/`. Most users don't know what files exist, what they say, or when they were last modified. The Memory Explorer makes this opaque system visible: audit what Claude "knows" about each project, see when memories were last written, and understand the full context Claude loads before starting a session.

**Effort:** L

**Technical notes:** New `GET /api/memory` endpoint scans:
- `~/.claude/memory/` — global memory files
- `~/.claude/CLAUDE.md` — global instructions
- Per-project `CLAUDE.md` — discovered via project paths already in session data
- `~/.claude/projects/*/memory/` — per-project memory files
- `~/.claude/skills/`, `~/.claude/commands/`, `~/.claude/agents/`, `~/.claude/hooks/`
- `~/.claude/settings.json` — read-only display

Returns a structured tree with `{name, path, size_bytes, modified_at, content_preview}` per file. `GET /api/memory/file?path=` returns full content of a specific file.

**Security requirement:** Path-validate strictly: `os.path.realpath(requested)` must start with `os.path.realpath(~/.claude/)`. Reject any symlinks that would escape the directory. This is the only new file-read surface in the entire roadmap.

Frontend: "Memory" nav item in the app header. Tree-structured panel with expandable sections (Global, then per-project). Clicking a file opens it in a read-only Markdown renderer in a side panel with file size and last-modified timestamp. Read-only in this phase.

---

### 7. Per-Model Cost Breakdown

> The "Cost" tile in the StatsBar becomes clickable; a popover shows a per-model table with cost, tokens, session count, and percentage of total spend for the selected time range.

**User benefit:** When mixing Opus and Sonnet sessions, you need to know how much each model contributes. This answers "would switching my default model meaningfully reduce my costs?" without opening a spreadsheet.

**Effort:** S

**Technical notes:** New `GET /api/stats/by-model?time_range=` endpoint groups by model and returns `[{model, session_count, cost_usd, input_tokens, output_tokens, pct_of_total}]`. Alternatively, compute client-side from the existing session list (no backend change). StatsBar cost tile gets a click handler. Dropdown/popover using existing `modelShort` badge styling — no new CSS patterns needed.

---

## Phase 3 — Control (Q4 2026)

_Let the user act, not just observe. Requires the observability foundations from Phases 1 and 2._

### 8. Budget Guardrails

> Set daily and weekly USD budgets stored in the config file; the WebSocket broadcast includes budget breach status; when exceeded, a persistent red banner appears and optionally writes a flag file that a Claude Code PreToolUse hook can read.

**User benefit:** Prevents accidental overspend when leaving multiple sessions running unattended. Turns the dashboard from a passive cost display into an active safety net.

**Effort:** M

**Technical notes:** Config schema in `~/.claude/claude-sessions-ui-config.json`: `{daily_budget_usd, weekly_budget_usd, alert_threshold_pct}`. New `GET /api/config` and `PUT /api/config` endpoints. The WebSocket broadcast loop (which already computes costs) gains a `budget_status: {daily: {budget, spent, pct, exceeded}, weekly: {...}}` field. Frontend renders a persistent red banner below StatsBar when any budget is exceeded. Opt-in hook integration: write `~/.claude/budget-exceeded.flag` when `exceeded` flips to true; a PreToolUse hook can read this and warn before expensive tool calls. Documented but not automatic.

---

### 9. Batch Operations

> Multi-select sessions from the session grid; bulk actions: Summarize All (Ollama queue with progress), Export Transcripts (ZIP download), Cost Report (CSV download).

**User benefit:** Processing 40 unsummarized sessions from last week one at a time is tedious. Bulk summarize queues them all in one click. Bulk export enables project archival or handoffs without manual one-by-one transcript downloads.

**Effort:** M

**Technical notes:** "Select" toggle button in the toolbar puts cards into multi-select mode (checkboxes appear on each card). A floating action bar at the bottom of the screen shows selected count + action buttons. Endpoints: `POST /api/batch/summarize` (body: `{session_ids: [...]}`) processes sequentially through Ollama with progress events via SSE or WebSocket; `POST /api/batch/export` returns a ZIP file (Python's built-in `zipfile` module — no new dependencies) containing one Markdown file per session; `POST /api/batch/cost-report` returns a CSV with per-session cost breakdown.

---

### 10. Persistent User Preferences

> Filter tab, sort mode, time range, view mode (Sessions vs. Projects), and selected project filter persist across page reloads and browser restarts.

**User benefit:** Every page reload resets the dashboard to "All / 1d / Recent" defaults. A user who always works in "Active / 1w / Cost" hits three buttons every time they open the dashboard. A small fix with outsized daily friction reduction.

**Effort:** S

**Technical notes:** Pure frontend change. On mount, read from `localStorage` under key `claude-sessions-ui-prefs`. On every filter/sort/timeRange/viewMode change, write back immediately. Schema: `{filter, sort, timeRange, selectedProject, viewMode}`. Touches only `App.jsx` — the state declarations and the effect that reads initial values on mount.

---

## Architectural Notes

### Backend file size threshold

`backend.py` is ~1,400 lines today. With these 10 features it will approach 2,500+ lines. The CLAUDE.md convention says "keep it single-file unless it grows beyond ~1,000 lines" — that threshold is already past. When `backend.py` exceeds **2,000 lines**, extract route handlers into a `routes/` package using FastAPI `APIRouter`, keeping core logic (JSONL parsing, cost calculation, caching) in `backend.py`. This is _when_, not _if_.

### No new frontend dependencies

Charts (Features 3, 5) use [uPlot](https://github.com/leeoniya/uPlot) (~35 KB) or raw SVG. Date picker (Feature 2) and multi-select (Feature 9) use native HTML elements (`<input type="date">`, `<input type="checkbox">`). No component library, no heavy charting library, no TypeScript.

### New SQLite tables are still derived caches

`session_messages` (FTS5 for Feature 1) and `daily_costs` (for Feature 5) must be backfill-capable — delete either table and it rebuilds from JSONL on next startup. Extend `_startup_backfill` to populate both. Show an "Indexing…" indicator in the app header while backfill runs, since initial indexing of large histories will take several seconds.

### Memory Explorer file security

`GET /api/memory/file?path=` is the only new file-read surface in this roadmap. It must strictly validate the requested path:

```python
requested = os.path.realpath(os.path.expanduser(path_param))
allowed   = os.path.realpath(os.path.expanduser("~/.claude"))
assert requested.startswith(allowed + os.sep)
```

Reject any path that resolves outside `~/.claude/` — including symlink traversals.

### Config file for persistent settings

Features 8 (budget guardrails) and 5 (cost trend threshold) write user configuration to `~/.claude/claude-sessions-ui-config.json`. This is a single flat JSON file. Do not add a `.env` file (per project conventions). Feature 10 (preferences) uses `localStorage` since it is display-only state with no backend dependency.

---

## What We Are Not Building

- **Authentication or multi-user support** — single-user local tool; the filesystem is the auth boundary
- **Cloud sync or remote access** — data stays in `~/.claude/` on your machine
- **An IDE plugin** — Claude Code already has IDE extensions; this dashboard complements them
- **Push notifications** (email, Slack, macOS notifications) — the in-app banner is sufficient for Phase 3
- **Semantic/vector search** — FTS5 keyword search covers the local use case; embedding infrastructure is overkill for a single-user tool
- **Session editing or deletion** — the dashboard reads Claude's state; it does not manage it
