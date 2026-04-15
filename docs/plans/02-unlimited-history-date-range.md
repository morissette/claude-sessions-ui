# Feature 2: Unlimited Session History + Custom Date Range

**Phase:** 1 — Depth | **Effort:** S | **Target:** Q2 2026

---

## Overview

Remove the current 6-month ceiling on session history by adding an "All" time range option and a custom date-range picker. Users can select any historical window — from "last hour" to "all time" — or specify exact start/end dates.

---

## Problem / Motivation

The current maximum time range is 6 months (`6m`). Long-running projects or power users hit this ceiling and cannot view older sessions. The SQLite historical store already contains all data — the 6-month limit is an artificial UI constraint, not a technical one. Removing it costs almost nothing in implementation effort and unlocks the full dataset.

Custom date ranges are necessary for cost reporting ("What did I spend in Q1?") and for comparing specific periods.

---

## Acceptance Criteria

- [ ] A new "All" option in the time range selector returns every session in the SQLite store
- [ ] A "Custom" option reveals a start date + end date picker; applying it filters sessions to that exact window
- [ ] Custom date ranges query SQLite using the existing `idx_sessions_last_active` index (no full scans)
- [ ] The "All" range uses a 30-second WebSocket poll interval (not 2s) to avoid hammering SQLite for static data
- [ ] Invalid custom ranges (end before start, future end date) show an inline validation error and do not fire a request
- [ ] When switching away from "Custom", the date pickers are hidden and the previous named range is restored
- [ ] Existing time range buttons (`1h`, `1d`, …, `6m`) are unaffected

---

## Backend Changes

### `TIME_RANGE_HOURS` — `backend.py` lines 73–81

Add `"all"` entry:

```python
TIME_RANGE_HOURS: dict[str, int | None] = {
    "1h":  1,
    "1d":  24,
    "3d":  72,
    "1w":  168,
    "2w":  336,
    "1m":  720,
    "6m":  4320,
    "all": None,   # None = no cutoff
}
```

### WebSocket endpoint — `backend.py` ~line 1296

Accept two additional query parameters: `start` and `end` (ISO 8601 strings).

```python
@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    time_range: str = "1d",
    start: str | None = None,
    end: str | None = None,
):
```

Pass `start`/`end` through to `get_sessions_for_range()`.

### `get_sessions_for_range()` — `backend.py` ~line 305

```python
async def get_sessions_for_range(
    time_range: str,
    start: str | None = None,
    end: str | None = None,
) -> list[dict]:
    hours = TIME_RANGE_HOURS.get(time_range)

    # Custom range always routes to SQLite
    if start or end:
        return await get_sessions_from_db(start=start, end=end)

    # "all" routes to SQLite with no cutoff
    if hours is None:
        return await get_sessions_from_db(start=None, end=None)

    # Existing routing logic unchanged
    if hours <= LIVE_HOURS:
        return await get_all_sessions(hours)
    return await get_sessions_from_db(hours=hours)
```

### `get_sessions_from_db()` — extend signature

```python
async def get_sessions_from_db(
    hours: int | None = None,
    start: str | None = None,
    end: str | None = None,
) -> list[dict]:
```

Build the `WHERE` clause dynamically:

```python
conditions = []
params = []

if start:
    conditions.append("last_active >= ?")
    params.append(start)
if end:
    conditions.append("last_active <= ?")
    params.append(end)
if hours is not None and not start and not end:
    cutoff = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
    conditions.append("last_active >= ?")
    params.append(cutoff)

where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
sql = f"SELECT * FROM sessions {where} ORDER BY last_active DESC"
```

### WebSocket poll interval

Add `"all"` to the interval logic:

```python
POLL_INTERVALS = {
    "live": 2,      # ≤24h
    "hist": 10,     # 3d–6m
    "all": 30,      # all / custom
}
```

### HTTP endpoint `GET /api/sessions`

Apply the same `start`/`end` query params for REST consumers.

---

## Frontend Changes

### `TIME_RANGES` array in `App.jsx` lines 8–16

```javascript
const TIME_RANGES = [
  { id: '1h',     label: '1h' },
  { id: '1d',     label: '1d' },
  { id: '3d',     label: '3d' },
  { id: '1w',     label: '1w' },
  { id: '2w',     label: '2w' },
  { id: '1m',     label: '1m' },
  { id: '6m',     label: '6m' },
  { id: 'all',    label: 'All' },
  { id: 'custom', label: 'Custom' },
]
```

### New state in `App.jsx`

```javascript
const [customStart, setCustomStart] = useState('')   // ISO date string
const [customEnd, setCustomEnd]     = useState('')
const [customError, setCustomError] = useState('')
```

### WebSocket URL construction

```javascript
function buildWsUrl(timeRange, customStart, customEnd) {
  const base = `ws://localhost:8765/ws?time_range=${timeRange}`
  if (timeRange === 'custom' && customStart && customEnd) {
    return `${base}&start=${customStart}T00:00:00Z&end=${customEnd}T23:59:59Z`
  }
  return base
}
```

Reconnect the WebSocket whenever `customStart` or `customEnd` changes (only when `timeRange === 'custom'`).

### Custom date picker UI

Appears inline in the toolbar when `timeRange === 'custom'`:

```jsx
{timeRange === 'custom' && (
  <span className="toolbar__date-range">
    <input type="date" value={customStart} onChange={...} max={customEnd || today} />
    <span>–</span>
    <input type="date" value={customEnd}   onChange={...} min={customStart} max={today} />
    {customError && <span className="toolbar__date-error">{customError}</span>}
  </span>
)}
```

Validation (run before reconnecting WebSocket):

```javascript
function validateCustomRange(start, end) {
  if (!start || !end) return 'Both dates are required'
  if (end < start)    return 'End date must be after start date'
  if (end > today)    return 'End date cannot be in the future'
  return ''
}
```

### No new component files needed

The date pickers are simple inline HTML elements in the existing toolbar markup in `App.jsx`. Add date-range styles to `App.css`.

---

## Security Considerations

- **ISO validation server-side:** Parse `start`/`end` with `datetime.fromisoformat()` in the WebSocket handler. Return a 400 WebSocket close code if parsing fails — never pass raw strings into SQL without parsing first.
- **Parameterized queries:** `start` and `end` are always bound via `?` parameters — not interpolated.
- **Range limits:** No hard server-side limit on range size (the feature's purpose is "unlimited"), but the 30s poll interval prevents abuse.

---

## Performance Considerations

- **`idx_sessions_last_active` covers all range queries** — the new `start`/`end` filter uses the same column already indexed. No additional indexes required.
- **"All" range:** Potentially returns thousands of sessions. The frontend already handles large lists via the existing sort/filter pipeline; no virtualization is added in this plan. If performance becomes an issue, pagination can be added in a follow-up.
- **30s poll for "All":** Avoids constant re-querying a large dataset that changes slowly.

---

## Testing Requirements

### Backend unit tests

- `test_time_range_all`: `TIME_RANGE_HOURS["all"]` is `None`
- `test_get_sessions_from_db_no_cutoff`: call with `hours=None`, verify no `WHERE` clause in query (mock `conn.execute` and capture SQL)
- `test_get_sessions_from_db_custom_range`: call with `start="2026-01-01"`, `end="2026-01-31"`, verify `BETWEEN`-style conditions in query
- `test_custom_range_invalid_iso`: pass `start="not-a-date"` to the WS endpoint, verify graceful error
- `test_custom_range_end_before_start`: `start="2026-04-10"`, `end="2026-04-01"` — frontend validation catches this; backend should also handle it gracefully

### Frontend tests (Vitest)

- `buildWsUrl` returns correct `&start=...&end=...` params when `timeRange='custom'`
- `validateCustomRange` returns error for end-before-start, future end, missing values
- Date pickers only render when `timeRange === 'custom'`

### Manual QA checklist

- [ ] Select "All" → sessions older than 6 months appear (if any exist in DB)
- [ ] Select "Custom", enter 2026-01-01 to 2026-01-31 → only January sessions shown
- [ ] Enter end before start → validation error appears, no request fired
- [ ] Switch back from "Custom" to "1d" → date pickers disappear, normal sessions shown
- [ ] Poll interval for "All" is visibly slower (check Network tab — no updates every 2s)

---

## Out of Scope

- Pagination for "All" results (follow-up if needed)
- Keyboard date entry shortcuts
- Relative custom ranges ("last 45 days")
- Per-query caching beyond the existing `_session_cache` mtime cache
