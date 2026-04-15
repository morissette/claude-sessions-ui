# Feature 10: Persistent User Preferences

**Phase:** 3 — Control | **Effort:** S | **Target:** Q4 2026

---

## Overview

Persist the user's filter tab, sort mode, time range, selected project, and view mode across page reloads using `localStorage`. Implemented entirely in the frontend via a `usePersistedState` custom hook — zero backend changes required.

---

## Problem / Motivation

Every time the user refreshes the page or reopens the browser, the dashboard resets to the defaults: filter "All", sort "Activity", time range "1d", no project, Sessions view. Users who always work in "1w" range or always filter by "Today" must re-apply their preferences on every visit. This is a small but persistent friction that a simple localStorage solution eliminates.

---

## Acceptance Criteria

- [ ] After selecting any preference (filter, sort, time range, view mode, project), refreshing the page restores that preference
- [ ] Preferences are stored under the key `"claude-sessions-ui-prefs"` in `localStorage`
- [ ] If `localStorage` is unavailable (e.g., private browsing with restrictions), the app falls back to defaults silently — no error thrown
- [ ] The stored schema includes a `version` field; if the version does not match the current schema version, preferences are reset to defaults (prevents stale schema from breaking the app after an upgrade)
- [ ] Preferences are applied before the first WebSocket connection is made, so the initial URL includes the correct `time_range`

---

## Backend Changes

None. This is a pure frontend change.

---

## Frontend Changes

### `usePersistedState` custom hook

Create `frontend/src/hooks/usePersistedState.js`:

```javascript
const PREFS_VERSION = 1

export function usePersistedState(key, defaultValue) {
  const [state, setState] = useState(() => {
    try {
      const raw = localStorage.getItem(key)
      if (!raw) return defaultValue
      const parsed = JSON.parse(raw)
      return parsed
    } catch {
      return defaultValue
    }
  })

  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(state))
    } catch {
      // localStorage unavailable (private mode, quota exceeded) — silently ignore
    }
  }, [key, state])

  return [state, setState]
}
```

### Preferences object in `App.jsx`

Replace the individual `useState` calls for persistent preferences with a single `usePersistedState` call:

```javascript
const PREFS_DEFAULTS = {
  version:         1,
  filter:          'all',
  sort:            'activity',
  timeRange:       '1d',
  selectedProject: null,
  viewMode:        'sessions',
}

const [prefs, setPrefs] = usePersistedState('claude-sessions-ui-prefs', PREFS_DEFAULTS)

// Version check — reset if schema changed
useEffect(() => {
  if (prefs.version !== PREFS_DEFAULTS.version) {
    setPrefs(PREFS_DEFAULTS)
  }
}, [])   // run once on mount
```

Destructure for use:

```javascript
const { filter, sort, timeRange, selectedProject, viewMode } = prefs
```

Update helpers — replace all `setFilter(x)`, `setSort(x)`, etc. with:

```javascript
const setFilter          = (v) => setPrefs(p => ({...p, filter:          v}))
const setSort            = (v) => setPrefs(p => ({...p, sort:            v}))
const setTimeRange       = (v) => setPrefs(p => ({...p, timeRange:       v}))
const setSelectedProject = (v) => setPrefs(p => ({...p, selectedProject: v}))
const setViewMode        = (v) => setPrefs(p => ({...p, viewMode:        v}))
```

This keeps the call sites throughout `App.jsx` unchanged — they still call `setFilter(...)` etc.

### Non-persistent state (unchanged)

The following remain as plain `useState` and are intentionally NOT persisted (ephemeral):

- `data` (WebSocket payload)
- `connected`
- `lastUpdate`
- `ollama`
- `selectedSessionId` (which detail overlay is open)
- `selectMode` / `selectedSessions` (batch selection)
- `batchProgress`
- `trendsExpanded`
- `searchQuery` / `searchResults`
- `customStart` / `customEnd` (custom date range — reset on each visit is intentional)

### Version migration strategy

When `PREFS_VERSION` is bumped (e.g., a new preference is added), the existing check resets to defaults. For backward-compatible additions (new key with a default), bump the version and add the new key to `PREFS_DEFAULTS`. For breaking changes, bump the version.

```javascript
// Example: version 2 adds 'compactView' preference
const PREFS_DEFAULTS = {
  version:         2,     // bumped
  filter:          'all',
  sort:            'activity',
  timeRange:       '1d',
  selectedProject: null,
  viewMode:        'sessions',
  compactView:     false,  // new in v2
}
```

Users upgrading from v1 get defaults — a one-time reset is acceptable.

### New file: `frontend/src/hooks/usePersistedState.js`

This is the only new file. No new CSS needed.

---

## Security Considerations

- `localStorage` is scoped to the origin (`localhost:8765` or `localhost:5173`) — no cross-origin access risk.
- Stored values are deserialized with `JSON.parse`. The result is used to set React state (string/null values). No `eval`, no `innerHTML`, no dynamic code execution from stored values.
- If stored data is malformed or tampered with, the `try/catch` in `usePersistedState` returns `defaultValue` — no crash.
- `localStorage` is not suitable for sensitive data. The stored preferences contain no secrets (just UI state).

---

## Performance Considerations

- `localStorage.getItem` is synchronous but fast (sub-millisecond for small payloads). The lazy initializer in `useState(() => ...)` ensures it runs only once at mount.
- `localStorage.setItem` is called via `useEffect` with a dep on `state`. Writing ~200 bytes to localStorage is negligible.
- The `version` check `useEffect` runs once on mount — O(1).

---

## Testing Requirements

### Frontend tests (Vitest)

Use `vi.stubGlobal('localStorage', localStorageMock)` to mock localStorage.

- `usePersistedState` reads default when localStorage is empty
- `usePersistedState` reads stored value on subsequent renders
- `usePersistedState` updates localStorage on state change
- `usePersistedState` returns default when stored JSON is malformed
- `usePersistedState` returns default when localStorage throws (quota exceeded)
- Version mismatch → preferences reset to defaults
- Version match → stored preferences applied

### Manual QA checklist

- [ ] Select time range "1w" → refresh page → "1w" still selected
- [ ] Select filter "Today" → refresh → "Today" filter active
- [ ] Select sort "Cost" → refresh → "Cost" sort active
- [ ] Switch to "Projects" view, select a project → refresh → Sessions view (project selection is not persisted — intentional: project list may have changed)
- [ ] Switch to "Memory" view → refresh → "Memory" tab active
- [ ] Open in private browsing (localStorage may be restricted) → no error, defaults used
- [ ] Simulate version mismatch: manually set `{"version":0,...}` in localStorage → refresh → defaults applied

### Verifying no regression

After implementing this feature, run through the full interaction checklist for all existing preferences to confirm nothing broke:

- [ ] Filter tabs (All / Active / Today) still work
- [ ] Sort buttons (Activity / Cost / Turns) still work
- [ ] Time range buttons still trigger WebSocket reconnect
- [ ] View mode toggle (Sessions / Projects / Memory) still works

---

## Out of Scope

- Cloud sync of preferences across devices
- Per-user preference profiles
- Import/export preferences as JSON
- Server-side preference storage
