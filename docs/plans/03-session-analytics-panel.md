# Feature 3: Session Analytics Panel

**Phase:** 1 — Depth | **Effort:** L | **Target:** Q2 2026

---

## Overview

Add an "Analytics" tab inside the existing `SessionDetail` overlay. The tab shows per-session usage charts: a turn-by-turn token timeline, cumulative cost curve, tool usage frequency bar chart, thinking-to-output ratio, and average turn duration. Charts are rendered as inline SVG — no third-party charting library.

---

## Problem / Motivation

The current session view shows only a static cost and token total. Users cannot see *how* cost was incurred over the course of a session — whether one expensive turn dominated, how tool usage is distributed, or how thinking tokens compare to output. This analytics panel gives developers the insight to optimize their prompting and tool usage patterns.

---

## Acceptance Criteria

- [ ] A second tab "Analytics" appears alongside "Transcript" in `SessionDetail`
- [ ] Clicking "Analytics" fetches data from `GET /api/sessions/{id}/analytics` and renders three charts
- [ ] Charts are lazy-loaded — no fetch happens until the Analytics tab is first clicked
- [ ] Turn-by-turn token timeline: stacked bar chart (input / output / cache per turn), x-axis = turn number
- [ ] Cumulative cost curve: line chart showing running cost total after each turn
- [ ] Tool usage: horizontal bar chart showing top 10 tools by call count
- [ ] Summary stats: thinking-to-output ratio and average turn duration in seconds
- [ ] Charts render correctly at both narrow (400px) and wide (900px) `SessionDetail` widths
- [ ] If a session has only 1 turn, charts render without error (edge case: single-bar state)
- [ ] Data is not re-fetched on tab switch — cached in component state after first load

---

## Backend Changes

### New endpoint: `GET /api/sessions/{session_id}/analytics`

Add in the HTTP endpoints section of `backend.py` (~line 1200), after the existing `/api/sessions/{id}/detail` endpoint:

```python
@app.get("/api/sessions/{session_id}/analytics")
async def get_session_analytics(session_id: str):
    data = await parse_session_analytics(session_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return data
```

**Response schema:**

```json
{
  "session_id": "abc123",
  "turns": [
    {
      "turn": 1,
      "input_tokens": 1200,
      "output_tokens": 340,
      "cache_create_tokens": 0,
      "cache_read_tokens": 900,
      "thinking_tokens": 512,
      "cost_usd": 0.0041,
      "duration_s": 3.2,
      "ts": "2026-04-10T14:22:01Z"
    }
  ],
  "cumulative_cost": [
    {"turn": 1, "cost_usd": 0.0041},
    {"turn": 2, "cost_usd": 0.0089}
  ],
  "tool_usage": [
    {"tool": "Read", "count": 14},
    {"tool": "Bash", "count": 9},
    {"tool": "Edit", "count": 6}
  ],
  "summary": {
    "total_turns": 12,
    "avg_turn_duration_s": 4.1,
    "thinking_ratio": 0.23,
    "peak_turn": 7,
    "peak_turn_cost_usd": 0.021
  }
}
```

### New function: `parse_session_analytics(session_id: str)`

Locate session JSONL path the same way `parse_session_file()` does — search within `CLAUDE_DIR` for `{session_id}.jsonl`. Return `None` if not found.

Parse the JSONL a second time for per-turn granularity. The existing `_session_cache` stores the aggregate result; analytics needs turn-level detail, so use a separate `_analytics_cache: dict[str, tuple[float, dict]]` (path → (mtime, analytics dict)) keyed by file path + mtime to avoid redundant I/O.

**Parsing logic:**

```python
turns = []
current_turn = {"input": 0, "output": 0, "cache_create": 0, "cache_read": 0,
                "thinking": 0, "start_ts": None, "end_ts": None, "tools": []}
turn_number = 0
tool_counts = Counter()

for line in jsonl_lines:
    entry = json.loads(line)
    role = entry.get("type") or entry.get("message", {}).get("role")

    if role == "user" and entry.get("message", {}).get("content"):
        # Start of a new turn
        if turn_number > 0:
            turns.append(finalize_turn(current_turn, turn_number))
        turn_number += 1
        current_turn = new_turn(entry["timestamp"])

    elif role == "assistant":
        msg = entry.get("message", {})
        usage = msg.get("usage", {})
        current_turn["input"]        += usage.get("input_tokens", 0)
        current_turn["output"]       += usage.get("output_tokens", 0)
        current_turn["cache_create"] += usage.get("cache_creation_input_tokens", 0)
        current_turn["cache_read"]   += usage.get("cache_read_input_tokens", 0)
        # thinking tokens from content blocks
        for block in msg.get("content", []):
            if block.get("type") == "thinking":
                current_turn["thinking"] += len(block.get("thinking", "").split()) * 1.3  # rough token est
        current_turn["end_ts"] = entry.get("timestamp")

    elif role == "tool":
        tool_name = entry.get("toolName") or entry.get("tool_name", "Unknown")
        tool_counts[tool_name] += 1
        current_turn["tools"].append(tool_name)
```

Duration per turn = `end_ts - start_ts` parsed as ISO timestamps. If `start_ts` or `end_ts` is missing, `duration_s = null`.

Thinking ratio = `sum(thinking_tokens) / sum(output_tokens)` (0.0 if no output).

---

## Frontend Changes

### `SessionDetail.jsx` — add tabs

Convert the existing transcript view into a two-tab layout. The current transcript content becomes the "Transcript" tab. Add an "Analytics" tab.

```jsx
// New state in SessionDetail
const [activeTab, setActiveTab] = useState('transcript')
const [analyticsData, setAnalyticsData] = useState(null)
const [analyticsLoading, setAnalyticsLoading] = useState(false)

// Tab header
<div className="session-detail__tabs">
  <button
    className={`session-detail__tab ${activeTab === 'transcript' ? 'active' : ''}`}
    onClick={() => setActiveTab('transcript')}
  >Transcript</button>
  <button
    className={`session-detail__tab ${activeTab === 'analytics' ? 'active' : ''}`}
    onClick={() => {
      setActiveTab('analytics')
      if (!analyticsData) fetchAnalytics()
    }}
  >Analytics</button>
</div>
```

Lazy fetch:

```javascript
async function fetchAnalytics() {
  setAnalyticsLoading(true)
  const res = await fetch(`/api/sessions/${session.session_id}/analytics`)
  setAnalyticsData(await res.json())
  setAnalyticsLoading(false)
}
```

### New component: `frontend/src/components/SessionAnalytics.jsx`

Props:

```javascript
{
  data: {
    turns: [],
    cumulative_cost: [],
    tool_usage: [],
    summary: {}
  },
  loading: bool
}
```

Three chart sub-components, all pure SVG:

**`TurnTokenChart`** — stacked bar chart

```jsx
// SVG viewBox="0 0 600 200"
// Each turn = one bar group (4 stacked rects: input, output, cache_create, cache_read)
// x-axis: turn numbers, y-axis: token count
// Color-coded to match existing TokenBar colors in SessionCard
```

**`CumulativeCostChart`** — polyline chart

```jsx
// SVG viewBox="0 0 600 120"
// Points: (turn_index * dx, height - cumulative_cost * scale)
// Filled area below the line with low-opacity fill
// Y-axis: cost labels formatted with fmtCost()
```

**`ToolUsageChart`** — horizontal bar chart

```jsx
// SVG viewBox="0 0 400 (top10 * 24)"
// Each tool = one <rect> and a <text> label
// Width = count / maxCount * maxBarWidth
// Show count as text at end of bar
```

**Summary stat tiles** (plain HTML, no SVG):

```jsx
<div className="analytics__stats">
  <div className="analytics__stat">
    <span className="analytics__stat-value">{summary.avg_turn_duration_s.toFixed(1)}s</span>
    <span className="analytics__stat-label">Avg turn</span>
  </div>
  <div className="analytics__stat">
    <span className="analytics__stat-value">{(summary.thinking_ratio * 100).toFixed(0)}%</span>
    <span className="analytics__stat-label">Thinking</span>
  </div>
  ...
</div>
```

### New CSS: `frontend/src/components/SessionAnalytics.css`

Key rules:

```css
.analytics__chart-title { font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase; }
.analytics__stats { display: flex; gap: 1rem; flex-wrap: wrap; margin-bottom: 1.5rem; }
.analytics__stat-value { font-size: 1.5rem; font-variant-numeric: tabular-nums; }
```

Charts use `width: 100%` SVGs with `preserveAspectRatio="xMidYMid meet"` so they scale with the detail panel width.

---

## Security Considerations

- `session_id` path parameter is validated to be alphanumeric + hyphens only before use in file path construction — reuse the same validation pattern used by the existing `/api/sessions/{id}/detail` endpoint.
- No user-controlled data is rendered as HTML (SVG attributes are set programmatically, not via `innerHTML`).

---

## Performance Considerations

- **`_analytics_cache`** prevents re-parsing the same JSONL file within a single server process lifetime. Invalidated on file mtime change — same pattern as `_session_cache`.
- **Lazy loading** means the analytics endpoint is only hit when the user explicitly clicks the tab. Most users viewing a session will never trigger the analytics fetch.
- **SVG chart size:** All charts are inline SVG with `<100` DOM nodes. No canvas, no WebGL, no virtualization needed.
- **Large sessions:** A session with 500 turns produces 500 bar groups. Cap the timeline chart at 200 turns (show first 200); add a "showing first 200 turns" notice above the chart if truncated.

---

## Testing Requirements

### Backend unit tests

- `test_parse_session_analytics_basic`: fixture JSONL with 3 turns → verify `turns` array length = 3, costs are positive, tool_usage populated
- `test_parse_session_analytics_single_turn`: 1-turn session → no divide-by-zero errors, `turns` length = 1
- `test_parse_session_analytics_no_tools`: session with no tool calls → `tool_usage = []`
- `test_parse_session_analytics_thinking`: JSONL with `thinking` content block → `thinking_ratio > 0`
- `test_analytics_cache_invalidation`: parse once, modify file mtime, parse again → fresh data returned
- `test_analytics_404`: nonexistent session_id → HTTP 404

### Frontend tests (Vitest)

- `SessionAnalytics` renders loading spinner when `loading=true`
- `CumulativeCostChart` renders correct number of polyline points
- `ToolUsageChart` caps at 10 tools even if data has 20
- `TurnTokenChart` renders correctly for 1-turn session (no crash)
- Analytics tab click triggers fetch only once (subsequent clicks don't re-fetch)

### Manual QA checklist

- [ ] Open any session with multiple turns → "Analytics" tab visible
- [ ] Click "Analytics" → spinner, then charts appear
- [ ] Click "Transcript" then "Analytics" again → no second network request
- [ ] Verify stacked bar colors match the TokenBar colors in the session card
- [ ] Open a 1-turn session → single bar renders without error
- [ ] Resize the SessionDetail panel → charts scale responsively

---

## Out of Scope

- Comparing analytics across multiple sessions
- Exporting charts as images
- Per-tool duration tracking (tool timing is not currently in the JSONL)
- Streaming the analytics response for very long sessions (sync response is fine up to ~500 turns)
