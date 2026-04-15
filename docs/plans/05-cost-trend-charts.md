# Feature 5: Cost Trend Charts + Budget Alerts

**Phase:** 2 — Intelligence | **Effort:** L | **Target:** Q3 2026

---

## Overview

Add a collapsible "Trends" section below the StatsBar showing a daily/weekly cost chart broken down by model, with an optional budget threshold line. Budget limits are stored in a new config file (`~/.claude/claude-sessions-ui-config.json`) managed via a new `GET/PUT /api/config` API. This feature introduces the config infrastructure that Feature 8 (Budget Guardrails) builds on.

---

## Problem / Motivation

The current dashboard shows total cost for the selected time window, but gives no picture of how spending trends over time. Users cannot answer: "Am I spending more this week than last week?" or "Which model is driving cost increases?" The chart fills this gap. Budget alerts paired with the chart complete the feedback loop — users set a target, see when they approach it, and can adjust their Claude usage accordingly.

---

## Acceptance Criteria

- [ ] A "Trends" section below StatsBar is collapsed by default; a chevron button expands/collapses it
- [ ] When expanded, a stacked bar chart shows daily cost for the last N days, with each model's contribution as a separate color
- [ ] If a daily budget is set, a horizontal dashed line appears at the budget amount
- [ ] A budget input (inline, inline-edit pattern) in the Trends header allows setting `daily_budget_usd`; changes are saved via `PUT /api/config`
- [ ] The `GET /api/trends?range=4w` endpoint returns daily cost data for the last 28 days
- [ ] The `daily_costs` table is backfilled from JSONL on startup and updated incrementally
- [ ] Budget values of `null` disable the budget line — no validation error for empty budget
- [ ] The chart rescales gracefully when budget line exceeds or is below all bars

---

## Backend Changes

### Config file

Location: `~/.claude/claude-sessions-ui-config.json`

Schema:
```json
{
  "daily_budget_usd": null,
  "weekly_budget_usd": null
}
```

Constants in `backend.py`:

```python
CONFIG_PATH = Path.home() / ".claude" / "claude-sessions-ui-config.json"

def read_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {"daily_budget_usd": None, "weekly_budget_usd": None}

def write_config(data: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(data, indent=2))
```

### New SQLite table: `daily_costs`

Add to `init_db()` in `backend.py` after the `sessions` table:

```sql
CREATE TABLE IF NOT EXISTS daily_costs (
    date            TEXT PRIMARY KEY,   -- ISO date: "2026-04-10"
    total_cost_usd  REAL NOT NULL DEFAULT 0.0,
    model_breakdown TEXT NOT NULL DEFAULT '{}',  -- JSON: {"claude-sonnet-4-6": 1.23}
    session_count   INT  NOT NULL DEFAULT 0,
    last_synced_at  TEXT
);
```

- Derived cache — delete the table and restart to rebuild.
- `model_breakdown` stored as JSON text (SQLite has no native JSON type; use `json.dumps`/`json.loads`).

### New function: `backfill_daily_costs()`

Runs after `backfill_db()` on startup. Aggregates the `sessions` table (which is already populated) by date:

```python
async def backfill_daily_costs():
    def _run():
        with get_db() as conn:
            rows = conn.execute(
                "SELECT DATE(started_at) AS date, model, SUM(estimated_cost_usd), COUNT(*) "
                "FROM sessions GROUP BY date, model"
            ).fetchall()
            # Group by date, accumulate model breakdown
            by_date = {}
            for date, model, cost, count in rows:
                if date not in by_date:
                    by_date[date] = {"total": 0.0, "models": {}, "count": 0}
                by_date[date]["total"]          += cost
                by_date[date]["models"][model]  = by_date[date]["models"].get(model, 0.0) + cost
                by_date[date]["count"]          += count
            # Upsert into daily_costs
            for date, data in by_date.items():
                conn.execute(
                    "INSERT OR REPLACE INTO daily_costs VALUES (?, ?, ?, ?, ?)",
                    (date, data["total"], json.dumps(data["models"]),
                     data["count"], datetime.now(UTC).isoformat())
                )
            conn.commit()
    await asyncio.get_event_loop().run_in_executor(None, _run)
```

**Incremental updates:** in `upsert_session_to_db()`, after upserting the session row, update the `daily_costs` row for the session's date using `INSERT OR REPLACE` with re-aggregated data.

### New endpoint: `GET /api/trends`

```python
@app.get("/api/trends")
async def get_trends(range: str = "4w"):
    # Parse range: "4w" → 28 days, "3m" → 90 days
    days = parse_trend_range(range)
    cutoff = (date.today() - timedelta(days=days)).isoformat()

    def _query():
        with get_db() as conn:
            rows = conn.execute(
                "SELECT date, total_cost_usd, model_breakdown, session_count "
                "FROM daily_costs WHERE date >= ? ORDER BY date",
                (cutoff,)
            ).fetchall()
        return rows

    rows = await asyncio.get_event_loop().run_in_executor(None, _query)
    config = read_config()

    days_data = [
        {
            "date": r[0],
            "total_cost_usd": r[1],
            "by_model": json.loads(r[2]),
            "session_count": r[3],
        }
        for r in rows
    ]

    return {
        "days": days_data,
        "daily_budget_usd": config.get("daily_budget_usd"),
        "weekly_budget_usd": config.get("weekly_budget_usd"),
    }
```

Valid `range` values: `"2w"` (14d), `"4w"` (28d), `"3m"` (90d). Default `"4w"`.

### New endpoints: `GET /api/config` and `PUT /api/config`

```python
@app.get("/api/config")
async def get_config():
    return read_config()

@app.put("/api/config")
async def put_config(body: dict):
    allowed_keys = {"daily_budget_usd", "weekly_budget_usd"}
    config = read_config()
    for k, v in body.items():
        if k in allowed_keys:
            config[k] = float(v) if v is not None else None
    write_config(config)
    return config
```

---

## Frontend Changes

### New state in `App.jsx`

```javascript
const [trendsExpanded, setTrendsExpanded] = useState(false)
```

### Trends section markup (in App.jsx, below StatsBar)

```jsx
<section className="trends">
  <button className="trends__toggle" onClick={() => setTrendsExpanded(e => !e)}>
    Cost Trends
    <span className={`trends__chevron ${trendsExpanded ? 'open' : ''}`}>▾</span>
  </button>
  {trendsExpanded && <TrendsChart timeRange={timeRange} />}
</section>
```

### New component: `frontend/src/components/TrendsChart.jsx`

Uses a `useTrends` hook:

```javascript
function useTrends(timeRange) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    setLoading(true)
    fetch('/api/trends?range=4w')
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false) })
  }, [timeRange])

  return { data, loading }
}
```

**Chart rendering (inline SVG):**

- `viewBox="0 0 700 180"`
- X-axis: one column per day (bar width = `700 / numDays - 2px gap`)
- Y-axis: auto-scaled to `max(max_daily_cost, daily_budget * 1.1)`
- Each bar = stacked `<rect>` elements, one per model, colored by model (reuse `modelShort` color classes)
- Budget line: horizontal `<line>` at `y = height - (budget / maxCost) * chartHeight`, `stroke-dasharray="4 2"`, color = `var(--color-warning)`
- X-axis labels: date labels every 7 days to avoid crowding

**Budget input (inline edit):**

```jsx
function BudgetInput({ value, onSave }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value ?? '')

  return editing ? (
    <span>
      $<input type="number" min="0" step="0.01" value={draft}
              onChange={e => setDraft(e.target.value)} />
      <button onClick={() => { onSave(parseFloat(draft) || null); setEditing(false) }}>Save</button>
      <button onClick={() => setEditing(false)}>Cancel</button>
    </span>
  ) : (
    <span onClick={() => setEditing(true)}>
      Daily budget: {value != null ? `$${value.toFixed(2)}` : 'not set'} ✎
    </span>
  )
}
```

`onSave` calls `PUT /api/config` with `{ daily_budget_usd: newValue }`.

### New CSS: `frontend/src/components/TrendsChart.css`

---

## Security Considerations

- `PUT /api/config` only accepts `daily_budget_usd` and `weekly_budget_usd` keys (allowlist). Any other keys are silently ignored.
- Budget values are cast to `float` server-side — arbitrary JSON cannot be stored in the config.
- `CONFIG_PATH` is hardcoded to `~/.claude/claude-sessions-ui-config.json` — no user-controlled paths.
- `write_config()` writes atomically via `Path.write_text()` (single syscall on most platforms). For production robustness, consider a write-to-temp-then-rename pattern, but this is optional for v1.

---

## Performance Considerations

- `daily_costs` table has at most ~180 rows for 6 months of data. All queries are O(1) index lookups by date.
- `backfill_daily_costs()` runs once on startup in a background thread — does not block the WebSocket loop.
- Incremental updates on `upsert_session_to_db()` update a single date row — O(1).
- The frontend fetches trends only when the section is expanded, not on every WebSocket message.

---

## Testing Requirements

### Backend unit tests

- `test_read_config_missing_file`: `CONFIG_PATH` not present → returns defaults
- `test_write_read_config_roundtrip`: write config, read it back, values match
- `test_put_config_ignores_unknown_keys`: `PUT /api/config` with `{"evil_key": "x"}` → key not saved
- `test_backfill_daily_costs_aggregation`: insert 3 sessions on same date, verify `daily_costs` row has correct total
- `test_get_trends_empty_db`: no data → `{days: [], daily_budget_usd: null}`
- `test_get_trends_with_budget`: budget set → `daily_budget_usd` returned in response

### Frontend tests (Vitest)

- `TrendsChart` renders the correct number of bar columns for the data
- `BudgetInput` switches to edit mode on click, calls `onSave` with parsed float
- Budget line SVG element is not rendered when `daily_budget_usd` is null
- Trends section is collapsed by default

### Manual QA checklist

- [ ] Expand Trends section → chart loads with daily bars
- [ ] Each bar is colored by model (check against Sessions view model badges)
- [ ] Set daily budget to $5 → dashed line appears at correct height
- [ ] Clear budget (empty input, save) → line disappears
- [ ] Switch time range → chart refreshes
- [ ] Day with zero sessions → bar absent (not a zero-height bar causing layout issues)

---

## Out of Scope

- Weekly trend view (daily is sufficient for v1)
- Per-project trend breakdown (see Feature 4)
- Export trends data to CSV (see Feature 9)
- Alerts/notifications when budget is exceeded (that is Feature 8)
- Historical trend data beyond the `daily_costs` backfill range
