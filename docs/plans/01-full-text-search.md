# Feature 1: Full-Text Session Search

**Phase:** 1 — Depth | **Effort:** M | **Target:** Q2 2026

---

## Overview

Add a keyword search input to the toolbar that searches across all session transcripts. Results display as a list of matching snippets with session title, timestamp, and role (user/assistant). For sessions within the live 24-hour window, search runs via JSONL line scanning. For historical sessions, search uses an FTS5 virtual table in SQLite.

---

## Problem / Motivation

Users accumulate dozens or hundreds of sessions. There is currently no way to find a session by what was discussed — only by cost, date, or whether it is active. A developer who remembers "I asked Claude about rate limiting last week" has no way to find that session without opening each one manually.

Full-text search turns the session history into a searchable knowledge base.

---

## Acceptance Criteria

- [ ] Typing in the search box returns results within 500ms for up to 6 months of history
- [ ] Each result shows: session title, project name, matched snippet (±50 chars of context), timestamp of the matching message, role (user / assistant)
- [ ] Snippets highlight the matched keyword(s) with `<mark>` tags
- [ ] Clearing the search box restores the normal session list
- [ ] Search works across both live (≤24h) JSONL sessions and historical SQLite sessions
- [ ] SQL injection via search input is impossible — all FTS5 queries use parameterized statements
- [ ] Searching while no results exist shows an empty state message, not an error
- [ ] The feature degrades gracefully if the FTS index is still being built (shows partial results or a "building index…" indicator)

---

## Backend Changes

### New SQLite table: `session_messages` (FTS5)

Add to `init_db()` in `backend.py` after the existing `sessions` table DDL (around line 177):

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS session_messages USING fts5(
    session_id UNINDEXED,
    role,
    content,
    ts UNINDEXED,
    tokenize = 'porter ascii'
);
```

- `UNINDEXED` columns are stored but not tokenized — keeps the index compact.
- `porter ascii` stemming lets "running" match "run".
- No foreign key — FTS5 virtual tables don't support them.

**Backfill on startup:** new async task `backfill_fts()` runs after `backfill_db()`. Iterates all JSONL files, extracts `user`/`assistant` messages, bulk-inserts into `session_messages` via `executemany`. Skips sessions already present (check with `SELECT 1 FROM session_messages WHERE session_id = ? LIMIT 1`).

**Incremental sync:** when a session is upserted into the `sessions` table (existing `upsert_session_to_db()`), also delete existing `session_messages` rows for that session and re-insert the latest messages. This keeps the FTS index current without a full rebuild.

### New endpoint: `GET /api/search`

```
GET /api/search?q=rate+limiting&time_range=1w&limit=20
```

**Request parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `q` | string | required | Search query (1–200 chars) |
| `time_range` | string | `"1d"` | Same values as WebSocket `time_range` |
| `limit` | int | 20 | Max results (1–100) |

**Response schema:**

```json
{
  "query": "rate limiting",
  "results": [
    {
      "session_id": "abc123",
      "project_name": "my-api",
      "session_title": "Implement rate limiting middleware",
      "role": "user",
      "snippet": "...how should I implement **rate limiting** for the...",
      "ts": "2026-04-10T14:22:01Z",
      "score": 1.42
    }
  ],
  "total": 7,
  "index_ready": true
}
```

- `snippet`: 100-char window around the match, with `**term**` markers (frontend converts to `<mark>`)
- `score`: FTS5 `rank` value (higher = more relevant)
- `index_ready`: `false` during initial backfill so the frontend can show a notice

**Implementation in `backend.py`** (add in the HTTP endpoints section, ~line 1200):

```python
@app.get("/api/search")
async def search_sessions(q: str, time_range: str = "1d", limit: int = 20):
    q = q.strip()[:200]
    if not q:
        return {"query": q, "results": [], "total": 0, "index_ready": True}

    hours = TIME_RANGE_HOURS.get(time_range, 24)
    cutoff = datetime.now(UTC) - timedelta(hours=hours)

    results = []

    # Historical path: FTS5
    if hours > LIVE_HOURS:
        results = await search_fts(q, cutoff, limit)
    else:
        # Live path: grep JSONL
        results = await search_jsonl_live(q, cutoff, limit)

    return {
        "query": q,
        "results": results[:limit],
        "total": len(results),
        "index_ready": not _fts_backfill_running,
    }
```

**New helper: `search_fts(query, cutoff, limit)`**

```python
async def search_fts(query: str, cutoff: datetime, limit: int) -> list[dict]:
    def _query():
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT sm.session_id, sm.role, sm.ts,
                       snippet(session_messages, 2, '**', '**', '...', 16) AS snippet,
                       rank
                FROM session_messages sm
                JOIN sessions s ON sm.session_id = s.session_id
                WHERE session_messages MATCH ?
                  AND s.last_active >= ?
                ORDER BY rank
                LIMIT ?
                """,
                (query, cutoff.isoformat(), limit),
            ).fetchall()
        return rows
    rows = await asyncio.get_event_loop().run_in_executor(None, _query)
    # Enrich with session metadata from _session_cache or DB
    ...
```

**New helper: `search_jsonl_live(query, cutoff, limit)`**

Iterates JSONL files modified after `cutoff`, scans line-by-line for `query` (case-insensitive), extracts matching `content` with 50-char context window. Returns same schema as FTS results.

### Module-level flag

```python
_fts_backfill_running: bool = False
```

Set to `True` at start of `backfill_fts()`, `False` on completion.

---

## Frontend Changes

### State additions in `App.jsx`

```javascript
const [searchQuery, setSearchQuery] = useState('')
const [searchResults, setSearchResults] = useState(null)   // null = not searching
const [searchLoading, setSearchLoading] = useState(false)
```

### Debounced search effect

```javascript
useEffect(() => {
  if (!searchQuery.trim()) { setSearchResults(null); return }
  const t = setTimeout(async () => {
    setSearchLoading(true)
    const res = await fetch(`/api/search?q=${encodeURIComponent(searchQuery)}&time_range=${timeRange}`)
    const data = await res.json()
    setSearchResults(data)
    setSearchLoading(false)
  }, 300)
  return () => clearTimeout(t)
}, [searchQuery, timeRange])
```

### Toolbar addition

Search input placed between the filter tabs and the time range selector:

```jsx
<input
  className="toolbar__search"
  type="search"
  placeholder="Search sessions…"
  value={searchQuery}
  onChange={e => setSearchQuery(e.target.value)}
/>
```

### Conditional rendering in main content area

When `searchResults !== null`, render `<SearchResults>` instead of the session list:

```jsx
{searchResults !== null
  ? <SearchResults results={searchResults} loading={searchLoading} onSelect={setSelectedSessionId} />
  : <div className="session-list">...</div>
}
```

### New component: `frontend/src/components/SearchResults.jsx`

Props:
```javascript
{
  results: { query, results: [], total, index_ready },
  loading: bool,
  onSelect: (sessionId) => void   // opens SessionDetail
}
```

Renders:
- Loading spinner while `loading`
- "Building search index…" notice if `!index_ready`
- Empty state if `results.length === 0`
- Result list: session title, project name, role badge, timestamp, snippet with `**term**` → `<mark>term</mark>` conversion

### New CSS: `frontend/src/components/SearchResults.css`

---

## Security Considerations

- **SQL injection:** FTS5 queries always use `?` parameter binding. The query string is never interpolated into SQL.
- **FTS5 special characters:** SQLite FTS5 will error on malformed queries (e.g. unmatched `"`). Wrap `_query()` in a `try/except sqlite3.OperationalError` and return empty results with a `parse_error: true` flag.
- **Input length:** Cap `q` at 200 characters server-side before any processing.
- **Path traversal:** `search_jsonl_live` iterates only files within `CLAUDE_DIR` — no user-controlled paths.

---

## Performance Considerations

- **FTS5 index size:** For 6 months of typical usage (~1,000 sessions, ~500KB JSONL each), the FTS5 index is estimated at 5–15MB — negligible.
- **Backfill time:** Run in a background thread pool; does not block startup or WebSocket connections. Use `PRAGMA journal_mode=WAL` (already set) to allow concurrent reads during backfill.
- **Live JSONL grep:** Limited to files modified within the last 24 hours. Early-exit per file once `limit` results are found.
- **Debounce:** 300ms debounce on the frontend prevents a query per keystroke.
- **Index freshness:** FTS rows are refreshed on every `upsert_session_to_db()` call — same cadence as the `sessions` table cache.

---

## Testing Requirements

### Backend unit tests (`tests/test_backend.py`)

- `test_search_fts_basic`: insert fixture rows into `session_messages`, call `search_fts("keyword", ...)`, verify snippet and session_id returned
- `test_search_fts_sql_injection`: pass `'"; DROP TABLE sessions; --'` as query, verify empty result and no DB corruption
- `test_search_fts_special_chars`: pass `"rate (limiting)"` — unmatched parens — verify graceful empty result, not 500
- `test_search_jsonl_live`: create temp JSONL with known content, call `search_jsonl_live("keyword", ...)`, verify match returned
- `test_search_empty_query`: `q=""` returns `{results: [], total: 0}`

### Frontend component tests (Vitest)

- `SearchResults` renders loading spinner when `loading=true`
- `SearchResults` renders empty state when `results=[]`
- `SearchResults` converts `**term**` to `<mark>term</mark>` in snippets
- Search input in `App` debounces — only one fetch after rapid typing

### Manual QA checklist

- [ ] Type a word that appears in a recent session transcript → results appear within 500ms
- [ ] Click a result → `SessionDetail` opens for that session
- [ ] Clear the search box → normal session list returns
- [ ] Search with `' OR 1=1 --` → no error, empty results
- [ ] Search while FTS backfill is running → "building index" notice visible
- [ ] Search with `time_range=6m` → results from older sessions appear

---

## Out of Scope

- Semantic / vector search (not in ROADMAP)
- Searching within a single session (that's the existing `SessionDetail` transcript view)
- Regex or wildcard search syntax
- Saved/pinned searches
- Search result ranking tuning beyond FTS5 defaults
