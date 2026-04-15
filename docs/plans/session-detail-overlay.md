# Plan: Session Detail Overlay

## Overview

Clicking a session card opens a full-screen modal overlay that shows the complete conversation history — all user messages, assistant replies, tool calls, and tool results. Currently the UI shows only truncated summaries; this feature exposes the raw JSONL data as a readable chat interface.

---

## Architecture

- **Backend**: new `GET /api/sessions/{session_id}/detail` endpoint parses the JSONL file and returns structured message objects with pagination support.
- **Frontend**: `SessionDetail.jsx` modal rendered at the App level (so it overlays everything), opened by clicking a `SessionCard`.
- **No SQLite dependency**: reads directly from JSONL — this is a live read, not historical.

---

## Step 1: Backend — Session Detail Endpoint (`backend.py`)

### New helper: `find_session_file(session_id: str) -> Path | None`

Scans `~/.claude/projects/` for `{session_id}.jsonl`. Returns `None` if not found.

```python
def find_session_file(session_id: str) -> Path | None:
    for path in CLAUDE_DIR.glob(f"projects/*/{session_id}.jsonl"):
        return path
    return None
```

### New helper: `parse_session_detail(path: Path, offset: int = 0, limit: int = 200) -> dict`

Reads JSONL, parses each line into a normalized message object, applies pagination.

**Message types to handle:**

| JSONL `type` | Role | Rendered as |
|---|---|---|
| `user` with `content` str | user | Chat bubble |
| `assistant` | assistant | Chat bubble (may include `thinking` blocks) |
| `tool_use` | assistant | Collapsible tool call block |
| `tool_result` | tool | Collapsible result block (paired with tool_use by `tool_use_id`) |
| `summary` | system | Italicized summary block |

**Tool pairing**: Build a `tool_name_map: dict[str, str]` mapping `tool_use_id → tool_name` as a first pass through the file, then use it when rendering `tool_result` entries.

**Return shape:**
```python
{
    "session_id": str,
    "total_messages": int,       # raw JSONL line count
    "offset": int,
    "limit": int,
    "messages": [
        {
            "id": int,           # line index
            "type": str,         # "user" | "assistant" | "tool_use" | "tool_result" | "summary"
            "role": str,
            "content": str | list,
            "tool_name": str | None,
            "tool_use_id": str | None,
            "timestamp": str | None,
            "thinking": str | None,
        },
        ...
    ]
}
```

### New endpoint: `GET /api/sessions/{session_id}/detail`

```python
@app.get("/api/sessions/{session_id}/detail")
async def session_detail(session_id: str, offset: int = 0, limit: int = 200):
    path = find_session_file(session_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Session not found")
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, parse_session_detail, path, offset, limit)
    return result
```

---

## Step 2: Frontend — SessionDetail Component

### New file: `frontend/src/components/SessionDetail.jsx`

Full-screen modal overlay with a message thread.

```jsx
export default function SessionDetail({ sessionId, onClose }) {
  const [detail, setDetail] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!sessionId) return
    setLoading(true)
    fetch(`/api/sessions/${sessionId}/detail`)
      .then(r => r.json())
      .then(d => { setDetail(d); setLoading(false) })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [sessionId])

  // Close on backdrop click or Escape key
  useEffect(() => {
    const handler = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  return (
    <div className="detail-overlay" onClick={onClose}>
      <div className="detail-panel" onClick={e => e.stopPropagation()}>
        <div className="detail-header">
          <h2>Session Detail</h2>
          <button className="detail-close" onClick={onClose}>✕</button>
        </div>
        <div className="detail-body">
          {loading && <div className="detail-loading">Loading…</div>}
          {error && <div className="detail-error">{error}</div>}
          {detail && <MessageThread messages={detail.messages} />}
        </div>
      </div>
    </div>
  )
}
```

### Sub-component: `MessageThread`

Renders each message as a styled bubble:

- **user**: right-aligned blue bubble
- **assistant**: left-aligned neutral bubble; `thinking` blocks rendered as collapsible `<details>`
- **tool_use**: collapsible `<details>` with tool name as summary, input JSON in `<pre>`
- **tool_result**: collapsible `<details>` with output, visually connected to its tool_use
- **summary**: full-width italicized card

### New file: `frontend/src/components/SessionDetail.css`

```css
.detail-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  z-index: 200;
  display: flex;
  align-items: stretch;
  justify-content: flex-end;
}

.detail-panel {
  width: min(680px, 100vw);
  height: 100vh;
  background: var(--bg-card);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: -4px 0 32px rgba(0, 0, 0, 0.3);
}

.detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.detail-body {
  flex: 1;
  overflow-y: auto;
  padding: 1rem 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

/* Message bubbles */
.msg-user { align-self: flex-end; background: var(--accent); color: white; border-radius: 1rem 1rem 0.25rem 1rem; padding: 0.5rem 0.75rem; max-width: 80%; }
.msg-assistant { align-self: flex-start; background: var(--bg-hover); border-radius: 1rem 1rem 1rem 0.25rem; padding: 0.5rem 0.75rem; max-width: 80%; }
.msg-tool { width: 100%; font-size: 0.8rem; }
.msg-summary { width: 100%; font-style: italic; color: var(--text-muted); border-left: 2px solid var(--border); padding-left: 0.75rem; }
```

---

## Step 3: App.jsx Integration

1. Import `SessionDetail` and `useState` for `selectedSessionId`
2. Add state: `const [selectedSessionId, setSelectedSessionId] = useState(null)`
3. Pass `onSelect={setSelectedSessionId}` to each `SessionCard`
4. Render `<SessionDetail>` conditionally:
   ```jsx
   {selectedSessionId && (
     <SessionDetail
       sessionId={selectedSessionId}
       onClose={() => setSelectedSessionId(null)}
     />
   )}
   ```

---

## Step 4: SessionCard.jsx Integration

Add `onSelect` prop. Make the card header (or entire card) clickable:

```jsx
export default function SessionCard({ session, ollama, onSelect }) {
  // ...
  return (
    <div className="session-card" onClick={() => onSelect?.(session.session_id)}>
      {/* existing content */}
    </div>
  )
}
```

Add `cursor: pointer` to `.session-card` in `SessionCard.css`.

---

## Step 5: Tests

### Backend tests (`tests/test_backend.py`)

New class `TestSessionDetail`:
- `test_find_session_file_returns_path` — creates a temp JSONL file, verifies `find_session_file` returns it
- `test_find_session_file_missing_returns_none` — verifies returns `None` for unknown session_id
- `test_parse_session_detail_user_message` — JSONL with one user message, checks message shape
- `test_parse_session_detail_tool_pairing` — verifies `tool_name` is correctly set on `tool_result` messages
- `test_parse_session_detail_pagination` — offset/limit slicing works correctly
- `test_detail_endpoint_404_unknown_session` — HTTP client call returns 404

### Frontend tests (`frontend/src/__tests__/SessionDetail.test.jsx`)

- `test_renders_loading_state` — while fetch pending, shows "Loading…"
- `test_renders_messages_on_success` — mock fetch resolves, messages appear
- `test_closes_on_escape_key` — `onClose` called when Escape pressed
- `test_closes_on_backdrop_click` — `onClose` called when overlay clicked

---

## Critical Files

| File | Change |
|------|--------|
| `backend.py` | `find_session_file()`, `parse_session_detail()`, `GET /api/sessions/{session_id}/detail` |
| `frontend/src/components/SessionDetail.jsx` | New modal component |
| `frontend/src/components/SessionDetail.css` | New styles |
| `frontend/src/App.jsx` | `selectedSessionId` state, render `<SessionDetail>` |
| `frontend/src/components/SessionCard.jsx` | `onSelect` prop, card clickable |
| `tests/test_backend.py` | `TestSessionDetail` class |
| `frontend/src/__tests__/SessionDetail.test.jsx` | New frontend tests |

---

## Pagination Strategy

- Default `limit=200` covers most sessions without client-side paging
- For very long sessions (>200 messages), expose "Load more" button in `SessionDetail` that fetches `?offset=N`
- `total_messages` in response drives whether to show "Load more"

---

## Edge Cases

- **Binary/base64 content** in tool results: truncate to 500 chars with "…[truncated]" suffix
- **Null timestamps**: some older JSONL entries lack timestamps — render without timestamp, don't crash
- **Malformed JSON lines**: wrap each `json.loads()` in try/except, skip bad lines
- **Empty sessions**: render "No messages" empty state
- **Sessions still being written**: file is append-only, so a read mid-write may miss the last partial line — wrap each line parse in try/except

---

## Verification

```bash
# Backend
pytest tests/ -v -k "TestSessionDetail"

# Frontend
cd frontend && npm test -- --reporter=verbose SessionDetail

# Manual
./dev.sh
# Click any session card → overlay slides in from right
# Press Escape or click backdrop → overlay closes
# Verify tool calls show as collapsible blocks
# Verify very long sessions show "Load more"
```
