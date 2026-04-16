# Features

A visual walkthrough of every feature in Claude Sessions UI.

---

## Dashboard Overview

The main view shows all Claude CLI sessions as cards, with aggregate stats, live WebSocket connection, and quick-access controls.

![Dashboard overview](images/feature-dashboard-overview.png)

---

## Stats Bar

The top bar aggregates across all visible sessions: total cost, session count, output tokens, cache reads, turns, and subagent count.

![Stats bar](images/feature-stats-bar.png)

Click the cost figure to expand a per-model breakdown (Sonnet, Opus, Haiku, synthetic) showing sessions, tokens, cost, and percentage share.

![Stats cost drilldown](images/feature-stats-cost-expanded.png)

---

## Budget Guardrails

When spending exceeds your configured daily budget, a red banner appears at the top of the dashboard. Dismiss it with the X — it reappears the next time the threshold is breached.

![Budget exceeded banner](images/feature-budget-guardrails-banner.png)

---

## Session Filtering & Sorting

Filter sessions by status (**All / Active / Today**) and sort by activity, cost, or turns. The toolbar also toggles between Sessions, Projects, and Select (batch) views.

![Filter controls](images/feature-filter-controls.png)

**Active filter** — shows only sessions with a live Claude process attached:

![Active filter](images/feature-filter-active.png)

**Today filter** — shows all sessions started today:

![Today filter](images/feature-filter-today.png)

**Sort by cost** — most expensive sessions first:

![Sort by cost](images/feature-sort-by-cost.png)

**Sort by turns** — sessions with the most back-and-forth first:

![Sort by turns](images/feature-sort-by-turns.png)

---

## Time Ranges

Switch between live and historical data via the range selector. Short ranges (`1h`, `1d`) read directly from JSONL files; longer ranges (`3d`–`6m`) query the SQLite historical cache.

| Range | Source |
|---|---|
| `1h` / `1d` | Live JSONL (fast path) |
| `3d` / `1w` / `2w` / `1m` / `6m` | SQLite historical store |

![1-hour range](images/feature-time-range-1h.png)

![3-day range](images/feature-time-range-3d.png)

![1-month range](images/feature-time-range-1m.png)

![6-month range](images/feature-time-range-6m.png)

A **custom date range** picker lets you query any arbitrary window:

![Custom date range](images/feature-time-range-custom.png)

---

## Full-Text Search

Search sessions and projects by content, queries, or metadata. Results show excerpts with matching snippets, session IDs, and timestamps.

**Searching sessions:**

![Search sessions](images/feature-search-sessions-view.png)

**Searching across projects:**

![Search projects](images/feature-search-projects-view.png)

---

## Session Cards

Each card shows session name, model, token/cost summary, turn count, tool tags, and subagent count. Active sessions get a green border and a PID badge.

![Active session card](images/feature-active-session-card.png)

Sessions with an AI summary show a ✦ prefix:

![Session card with summary](images/feature-session-card-with-summary.png)

Hover a card to reveal the "view details" link:

![Session card hover](images/feature-session-card-hover.png)

---

## Session Detail & Transcript

Click any session to open the detail overlay — a message viewer showing full user/assistant turns, thinking blocks, and tool call/result blocks. Tool and result entries are **collapsed by default** into compact single-line rows: an accent-bar (orange = tool, green = result), a colored pill badge (`TOOL` / `RESULT`), and the tool name. Click the `>` chevron to expand and read the full payload.

![Session detail overlay](images/feature-session-detail-overlay.png)

![Session detail transcript](images/feature-session-detail-transcript.png)

The header provides a **↓ Transcript** download (Markdown) and close controls:

![Session detail header](images/feature-session-detail-header.png)

Scroll through longer sessions with full message history:

![Session detail scrolled](images/feature-session-detail-overlay-scrolled.png)

---

## Export as Skill

From inside any session detail, export the session as a reusable Claude Code skill file. Choose **Global** (available in all projects) or **Local** (this project only).

![Export as skill](images/feature-session-detail-export-skill.png)

---

## Analytics Dashboard

The **Analytics** tab (top toolbar) provides a global view of Claude usage across all sessions, split into two panes:

**Session Analytics (left pane):**
- KPI tiles: total time spent, estimated time saved, cache efficiency %, cache savings (USD), avg cost/turn, avg tokens/turn
- Ranked lists: longest sessions, most expensive sessions, most turns, sessions with most subagents
- Projects by session count and by total cost
- Model distribution table (sessions, %, cost per model)
- Active hours histogram — 24-bar chart of session start times
- Top Tools bar chart — color-coded by category (file ops, search, code, agent, web, data) with legend

**Memory Analytics (right pane):**
- Total memory files + size across all `~/.claude/memory/` and project memory directories
- By-category breakdown of memory file directories
- Recently modified files (top 5)
- Largest files (top 5)
- **Customization** subsection: skills, commands, agents, hooks, plugins, permissions, env vars, todo file count
- **Knowledge Base** subsection: session summary coverage %, project memory count, plans count, memory entries by type (user/feedback/project/reference)

The time range selector applies to session metrics; memory and customization stats are always current.

![Analytics dashboard](images/feature-analytics-tab.png)

![Analytics charts section](images/feature-analytics-charts.png)

---

## Session Analytics

The **Analytics** tab inside session detail shows:
- Turn-by-turn token bar chart
- Cumulative cost line chart
- Tool usage breakdown
- Summary stats: turns, avg tokens/turn, thinking %, peak cost

![Session analytics](images/feature-session-detail-analytics.png)

![Session analytics charts](images/feature-session-analytics-charts.png)

---

## Cost Trends Chart

The **Cost Trends** panel shows a daily bar chart across the selected time range, with a dashed line at your configured daily budget. Bars are colored by model.

![Cost trends chart](images/feature-cost-trends-chart.png)

---

## Batch Operations

Enter **Select** mode to multi-select sessions. A bottom toolbar appears with three bulk actions:

- **Summarize** — generate Ollama summaries for all selected sessions
- **Export ZIP** — download all selected sessions as a ZIP archive
- **Cost CSV** — generate a CSV cost report for the selection

![Batch select mode](images/feature-batch-select-mode.png)

![Sessions selected](images/feature-batch-selected-sessions.png)

![Batch operations toolbar](images/feature-batch-operations-toolbar.png)

---

## AI Session Summaries (Ollama)

Sessions can be summarized on demand using a local Ollama model (Llama 3.2). Click the ✦ button on any card. Summaries are cached and displayed as the card title prefix.

![Summarize loading](images/feature-ollama-summarize-loading.png)

![Summarize result](images/feature-ollama-summarize-result.png)

---

## Savings Analytics

The green savings banner tracks money saved by using Ollama summaries instead of Claude API calls, and by skipping PRs. It shows total saved, summary count, and a scrolling ticker of skipped PR names.

![Savings banner](images/feature-savings-banner.png)

![Savings banner detail](images/feature-savings-banner-detail.png)

---

## Memory View

The **Memory** tab provides a file browser for your `~/.claude/` directory — settings, memory files, projects, commands, agents, skills, hooks, and todos. Click any file to view its contents in the right panel.

![Memory view](images/feature-memory-view.png)

![Memory view file selected](images/feature-memory-view-file-selected.png)

---

## Live WebSocket Indicator

The top-right corner shows the active Ollama model badge and a **Live** indicator when the WebSocket connection is established. It turns red and reconnects automatically on disconnect.

![WebSocket live indicator](images/feature-websocket-live-indicator.png)
