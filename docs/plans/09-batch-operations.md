# Feature 9: Batch Operations

**Phase:** 3 — Control | **Effort:** M | **Target:** Q4 2026

---

## Overview

Enable multi-select on session cards and provide three bulk actions: summarize all selected sessions via Ollama (with real-time progress), export transcripts as a ZIP archive, and generate a cost report as CSV. A "Select" toggle in the toolbar activates selection mode; a floating action bar at the bottom of the screen shows the count and action buttons.

---

## Problem / Motivation

Users with dozens of sessions need to act on groups, not individuals. Today, generating Ollama summaries or exporting transcripts requires clicking session-by-session. For a team retrospective ("export all sessions from this sprint") or routine maintenance ("summarize all unsummarized sessions"), batch operations save significant manual effort.

---

## Acceptance Criteria

- [ ] A "Select" button in the toolbar toggles selection mode on/off
- [ ] In selection mode, each `SessionCard` shows a checkbox; clicking the card (or checkbox) toggles selection
- [ ] A floating action bar appears at the bottom when ≥1 session is selected, showing count and three action buttons
- [ ] **Summarize All:** sends selected sessions to Ollama queue; per-session status (pending → in progress → done / error) shown with a progress indicator on each card
- [ ] **Export Transcripts:** triggers download of a ZIP file containing one `.txt` file per selected session
- [ ] **Cost Report:** triggers download of a `.csv` file with one row per selected session
- [ ] Actions are disabled (greyed out with tooltip) if Ollama is unavailable for Summarize
- [ ] Switching time range or closing the detail panel does not lose the current selection
- [ ] "Select All" / "Deselect All" shortcuts in the action bar
- [ ] Batch operations are independent of each other — user can export while a summarize batch is running

---

## Backend Changes

### `POST /api/batch/summarize` — SSE streaming endpoint

```python
from fastapi.responses import StreamingResponse

@app.post("/api/batch/summarize")
async def batch_summarize(body: dict):
    session_ids: list[str] = body.get("session_ids", [])[:50]  # cap at 50
    if not session_ids:
        raise HTTPException(status_code=400, detail="No session IDs provided")

    async def generate():
        for sid in session_ids:
            yield f"data: {json.dumps({'id': sid, 'status': 'pending'})}\n\n"
            try:
                await trigger_ollama_summary(sid)   # existing summary logic
                yield f"data: {json.dumps({'id': sid, 'status': 'done'})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'id': sid, 'status': 'error', 'error': str(e)})}\n\n"
        yield "data: {\"done\": true}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

Cap at 50 sessions to prevent accidental runaway Ollama loads.

**`trigger_ollama_summary(session_id)`:** Extract and reuse the existing Ollama call logic from `POST /api/sessions/{id}/summarize`. If Ollama is unavailable, raise an exception (caught above).

### `POST /api/batch/export` — ZIP download

```python
import io
import zipfile

@app.post("/api/batch/export")
async def batch_export(body: dict):
    session_ids: list[str] = body.get("session_ids", [])[:100]

    def build_zip() -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for sid in session_ids:
                transcript = get_session_transcript(sid)  # reuse existing logic
                if transcript:
                    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", sid)
                    zf.writestr(f"{safe_name}.txt", transcript)
        return buf.getvalue()

    zip_bytes = await asyncio.get_event_loop().run_in_executor(None, build_zip)
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=sessions-export.zip"},
    )
```

`get_session_transcript(sid)` — reuse the existing transcript logic from `GET /api/sessions/{id}/transcript`. Extract it into a helper if it is currently inline in the route handler.

### `POST /api/batch/cost-report` — CSV download

```python
import csv
import io

@app.post("/api/batch/cost-report")
async def batch_cost_report(body: dict):
    session_ids: list[str] = body.get("session_ids", [])[:100]

    def build_csv() -> str:
        sessions = [get_cached_session(sid) for sid in session_ids]
        sessions = [s for s in sessions if s is not None]

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "session_id", "project_name", "title", "model",
            "started_at", "last_active", "turns",
            "input_tokens", "output_tokens", "cache_create_tokens", "cache_read_tokens",
            "total_tokens", "estimated_cost_usd"
        ])
        for s in sessions:
            stats = s.get("stats", {})
            writer.writerow([
                s["session_id"],
                s.get("project_name", ""),
                s.get("title", ""),
                s.get("model", ""),
                s.get("started_at", ""),
                s.get("last_active", ""),
                s.get("turns", 0),
                stats.get("input_tokens", 0),
                stats.get("output_tokens", 0),
                stats.get("cache_create_tokens", 0),
                stats.get("cache_read_tokens", 0),
                stats.get("total_tokens", 0),
                stats.get("estimated_cost_usd", 0.0),
            ])
        return buf.getvalue()

    csv_str = await asyncio.get_event_loop().run_in_executor(None, build_csv)
    return Response(
        content=csv_str.encode("utf-8"),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=cost-report.csv"},
    )
```

**`get_cached_session(sid)`:** Look up the session in `_session_cache` by scanning for the matching session_id. If not in cache, attempt to find and parse the JSONL file.

---

## Frontend Changes

### State additions in `App.jsx`

```javascript
const [selectMode, setSelectMode] = useState(false)
const [selectedSessions, setSelectedSessions] = useState(new Set())
const [batchProgress, setBatchProgress] = useState({})  // {session_id: 'pending'|'in-progress'|'done'|'error'}
```

Reset `selectedSessions` when `selectMode` is turned off:

```javascript
function toggleSelectMode() {
  setSelectMode(s => {
    if (s) setSelectedSessions(new Set())
    return !s
  })
}
```

### Selection toggle handler

```javascript
function toggleSession(id) {
  setSelectedSessions(prev => {
    const next = new Set(prev)
    next.has(id) ? next.delete(id) : next.add(id)
    return next
  })
}
```

### Toolbar addition

```jsx
<button
  className={`toolbar__btn ${selectMode ? 'active' : ''}`}
  onClick={toggleSelectMode}
>
  {selectMode ? `Selecting (${selectedSessions.size})` : 'Select'}
</button>
```

### `SessionCard.jsx` — add checkbox in select mode

Pass `selectMode`, `isSelected`, and `onToggle` props:

```jsx
// In SessionCard
{selectMode && (
  <input
    type="checkbox"
    className="session-card__checkbox"
    checked={isSelected}
    onChange={onToggle}
    onClick={e => e.stopPropagation()}   // prevent detail overlay open
    aria-label={`Select session ${session.title}`}
  />
)}
```

When `selectMode` is true, clicking the card body (not the checkbox) also toggles selection instead of opening the detail overlay.

Also show `batchProgress[session.session_id]` status on the card when in batch:

```jsx
{batchProgress[session.session_id] && (
  <span className={`session-card__batch-status session-card__batch-status--${batchProgress[session.session_id]}`}>
    {batchProgress[session.session_id]}
  </span>
)}
```

### New component: `frontend/src/components/BatchActionBar.jsx`

Renders as a fixed footer bar when `selectedSessions.size > 0`:

```jsx
function BatchActionBar({ count, onSelectAll, onDeselectAll, onSummarize, onExport, onCostReport, ollamaAvailable }) {
  return (
    <div className="batch-action-bar">
      <span className="batch-action-bar__count">{count} selected</span>
      <button onClick={onSelectAll}>All</button>
      <button onClick={onDeselectAll}>None</button>
      <div className="batch-action-bar__actions">
        <button onClick={onSummarize} disabled={!ollamaAvailable} title={!ollamaAvailable ? 'Ollama not available' : ''}>
          Summarize
        </button>
        <button onClick={onExport}>Export ZIP</button>
        <button onClick={onCostReport}>Cost CSV</button>
      </div>
    </div>
  )
}
```

### Summarize batch handler in `App.jsx`

Uses `EventSource` for SSE:

```javascript
async function handleBatchSummarize() {
  const ids = [...selectedSessions]
  // Set all to pending
  setBatchProgress(Object.fromEntries(ids.map(id => [id, 'pending'])))

  const response = await fetch('/api/batch/summarize', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({session_ids: ids}),
  })

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''

  while (true) {
    const {done, value} = await reader.read()
    if (done) break
    buf += decoder.decode(value, {stream: true})
    const lines = buf.split('\n\n')
    buf = lines.pop()
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const event = JSON.parse(line.slice(6))
        if (event.id) {
          setBatchProgress(prev => ({...prev, [event.id]: event.status}))
        }
      }
    }
  }
}
```

Note: Using `fetch` + `ReadableStream` rather than `EventSource` because `EventSource` does not support `POST` requests.

### Export handlers

```javascript
async function handleBatchExport() {
  const res = await fetch('/api/batch/export', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({session_ids: [...selectedSessions]}),
  })
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = 'sessions-export.zip'; a.click()
  URL.revokeObjectURL(url)
}

async function handleBatchCostReport() {
  // Same pattern, different endpoint and filename
}
```

### New CSS: `frontend/src/components/BatchActionBar.css`

```css
.batch-action-bar {
  position: fixed;
  bottom: 0; left: 0; right: 0;
  z-index: 200;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 1.5rem;
  background: var(--surface);
  border-top: 2px solid var(--color-accent);
  box-shadow: 0 -4px 16px rgba(0,0,0,0.1);
}
.batch-action-bar__actions { margin-left: auto; display: flex; gap: 0.5rem; }
```

---

## Security Considerations

- **Session ID validation:** All `session_ids` in batch payloads are validated to be alphanumeric + hyphens (same pattern as existing single-session endpoints) before any file I/O.
- **ZIP content:** Filenames inside the ZIP are sanitized via `re.sub(r"[^a-zA-Z0-9_-]", "_", sid)` — no path traversal possible within the ZIP.
- **Rate limiting for Summarize:** Cap batch at 50 sessions. Ollama calls are sequential (not parallel) to avoid overwhelming the local model server.
- **CSV injection:** CSV values containing `=`, `+`, `-`, `@` that could trigger formula execution in Excel are not escaped in v1 (these are session IDs, titles, and model names — low XSS risk in a local app). Add escaping if this feature is ever exposed externally.
- **Body size:** FastAPI default max request body (1MB) is sufficient for a list of 100 session IDs (~10KB).

---

## Performance Considerations

- **ZIP export:** Built in memory (BytesIO). For 100 sessions at ~50KB transcript each, peak memory = ~5MB — acceptable.
- **Summarize:** Sequential Ollama calls. At ~5s per session, 50 sessions = ~4 minutes. SSE progress keeps the user informed; no timeout issues because SSE is a long-lived response.
- **CSV:** Pure in-memory CSV generation; ~100 rows is trivially fast.
- **No blocking the WebSocket loop:** All three batch endpoints use `run_in_executor` for any synchronous I/O.

---

## Testing Requirements

### Backend unit tests

- `test_batch_export_zip_structure`: POST with 2 session IDs → ZIP bytes contain 2 `.txt` files with correct names
- `test_batch_export_empty`: empty `session_ids` → 400 error
- `test_batch_export_invalid_session_id`: ID with path-traversal chars → 400 error
- `test_batch_cost_report_csv_columns`: POST with 1 session → CSV has correct headers and data row
- `test_batch_summarize_sse_format`: POST → response body starts with `data:` SSE lines
- `test_batch_summarize_cap`: 60 session IDs → only first 50 processed

### Frontend tests (Vitest)

- `BatchActionBar` renders Summarize button disabled when `ollamaAvailable=false`
- `toggleSession` adds/removes IDs from `selectedSessions` Set correctly
- Select All: all filtered session IDs added to `selectedSessions`
- Deselect All: `selectedSessions` becomes empty Set
- `batchProgress` status correctly updates card badge

### Manual QA checklist

- [ ] Click "Select" → session cards show checkboxes
- [ ] Check 3 sessions → action bar appears with "3 selected"
- [ ] Click "All" → all visible sessions selected
- [ ] Click "Export ZIP" → browser downloads `sessions-export.zip`
- [ ] Open ZIP → one `.txt` per session
- [ ] Click "Cost CSV" → browser downloads `cost-report.csv`; open in spreadsheet app — data correct
- [ ] Click "Summarize" → per-card status badges update (pending → done)
- [ ] Summarize with Ollama unavailable → button disabled with tooltip
- [ ] Turn off Select mode → action bar disappears, selection cleared

---

## Out of Scope

- Bulk deletion of sessions (ROADMAP explicitly prohibits writing/deleting)
- Parallel Ollama summarization (sequential is intentional to protect local resources)
- Per-project batch operations (select by project filter instead)
- Resuming interrupted batch summarizations
