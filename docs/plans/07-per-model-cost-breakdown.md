# Feature 7: Per-Model Cost Breakdown

**Phase:** 2 — Intelligence | **Effort:** S | **Target:** Q3 2026

---

## Overview

Make the "Cost" tile in `StatsBar` clickable. Clicking it opens an inline popover showing a table of per-model cost breakdown: model name, session count, total tokens, total cost, and percentage of total. Computed entirely client-side from the session list — no new backend endpoint required.

---

## Problem / Motivation

Users who switch between Opus, Sonnet, and Haiku often want to know which model is driving their bill. The total cost tile shows the aggregate but hides model-level detail. This feature answers "How much of my $12 this week came from Opus?" without requiring a separate page or endpoint.

Implementing client-side means the breakdown is always in sync with the currently displayed sessions and requires zero backend work.

---

## Acceptance Criteria

- [ ] Clicking the cost tile in `StatsBar` opens a popover directly below it
- [ ] The popover lists each model present in the current session list as a row
- [ ] Each row shows: model badge (matching existing color scheme), session count, token count, cost, and % of total
- [ ] Rows are sorted by cost descending
- [ ] Clicking outside the popover or pressing Escape closes it
- [ ] The popover does not overflow the viewport on small screens (repositions or scrolls)
- [ ] The popover renders correctly when only one model is present
- [ ] The cost tile reverts to its normal appearance when the popover is closed

---

## Backend Changes

None. The existing WebSocket payload includes the full `sessions` array, each with a `model` field and `stats.estimated_cost_usd`. The breakdown is computable client-side.

---

## Frontend Changes

### `StatsBar.jsx` — pass sessions array

`StatsBar` currently receives `stats` (the aggregated global stats object) and `timeRange`. Add `sessions` to its props:

```jsx
// In App.jsx
<StatsBar stats={data.stats} timeRange={timeRange} sessions={filteredSessions} />
```

`filteredSessions` is the already-filtered-and-sorted session array used to render the session list — same data the user is looking at.

### `StatsBar.jsx` — make cost tile interactive

```jsx
// New state
const [showModelBreakdown, setShowModelBreakdown] = useState(false)
const costTileRef = useRef(null)

// Cost tile (existing markup, add button wrapper and ref)
<div className="stats-bar__tile stats-bar__tile--cost" ref={costTileRef}>
  <button
    className="stats-bar__cost-btn"
    onClick={() => setShowModelBreakdown(v => !v)}
    aria-expanded={showModelBreakdown}
    aria-haspopup="true"
  >
    <span className="stats-bar__tile-value">{fmtCost(stats.total_cost_usd)}</span>
    <span className="stats-bar__tile-label">Total cost ▾</span>
  </button>
  {showModelBreakdown && (
    <ModelBreakdownPopover
      sessions={sessions}
      onClose={() => setShowModelBreakdown(false)}
    />
  )}
</div>
```

### New component: `ModelBreakdownPopover`

Define in `StatsBar.jsx` (not a separate file — it is only used here and is ~40 lines):

```jsx
function ModelBreakdownPopover({ sessions, onClose }) {
  // Close on outside click
  useEffect(() => {
    const handler = (e) => {
      if (!e.target.closest('.stats-bar__tile--cost')) onClose()
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [onClose])

  // Close on Escape
  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onClose])

  // Compute breakdown
  const byModel = {}
  for (const s of sessions) {
    const m = s.model || 'unknown'
    if (!byModel[m]) byModel[m] = { sessions: 0, tokens: 0, cost: 0 }
    byModel[m].sessions += 1
    byModel[m].tokens   += s.stats?.total_tokens ?? 0
    byModel[m].cost     += s.stats?.estimated_cost_usd ?? 0
  }
  const totalCost = Object.values(byModel).reduce((sum, r) => sum + r.cost, 0)
  const rows = Object.entries(byModel)
    .map(([model, d]) => ({ model, ...d, pct: totalCost > 0 ? d.cost / totalCost * 100 : 0 }))
    .sort((a, b) => b.cost - a.cost)

  return (
    <div className="model-breakdown-popover" role="dialog" aria-label="Cost by model">
      <table className="model-breakdown-popover__table">
        <thead>
          <tr><th>Model</th><th>Sessions</th><th>Tokens</th><th>Cost</th><th>%</th></tr>
        </thead>
        <tbody>
          {rows.map(r => (
            <tr key={r.model}>
              <td><span className={`model-badge model-badge--${modelShort(r.model).cls}`}>{modelShort(r.model).label}</span></td>
              <td>{r.sessions}</td>
              <td>{fmt(r.tokens)}</td>
              <td>{fmtCost(r.cost)}</td>
              <td>{r.pct.toFixed(1)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
```

Uses `modelShort()` and `fmt()` / `fmtCost()` already defined in `App.jsx`. These are passed as props or imported — since `ModelBreakdownPopover` lives in `StatsBar.jsx`, the formatters need to be accessible there. Options:

1. Pass formatters as props from `App.jsx` to `StatsBar.jsx` (preferred — keeps `StatsBar.jsx` self-contained)
2. Move formatters to a shared `utils.js` file

**Decision:** Pass as props. `StatsBar` already receives data from `App.jsx`; adding `fmt`, `fmtCost`, `modelShort` as props is consistent.

### CSS additions in `StatsBar.css`

```css
.stats-bar__cost-btn {
  all: unset;
  cursor: pointer;
  display: contents;  /* inherits tile layout */
}
.stats-bar__cost-btn:hover .stats-bar__tile-value { text-decoration: underline; }

.model-breakdown-popover {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  z-index: 100;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  box-shadow: 0 4px 16px rgba(0,0,0,0.12);
  min-width: 340px;
  padding: 0.75rem;
}
.model-breakdown-popover__table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}
.model-breakdown-popover__table th,
.model-breakdown-popover__table td {
  padding: 0.3rem 0.5rem;
  text-align: right;
}
.model-breakdown-popover__table th:first-child,
.model-breakdown-popover__table td:first-child { text-align: left; }
```

---

## Security Considerations

- Entirely client-side computation on data already in the browser — no new server attack surface.
- Model names from the session payload are used only as display strings and CSS class lookups, not as HTML injection vectors (React escapes text content by default).

---

## Performance Considerations

- The breakdown computation is O(n) over the session list. For 1,000 sessions, this is a negligible client-side operation.
- The popover mounts only when opened. No cost when closed.

---

## Testing Requirements

### Frontend tests (Vitest)

- `ModelBreakdownPopover` renders correct row count for 3 different models
- Row sorting: highest cost model appears first
- Percentage calculation: 3 models with costs $3, $1, $1 → 60%, 20%, 20%
- Clicking outside the cost tile closes the popover (simulate `mousedown` event)
- Pressing Escape closes the popover
- Single-model case: one row, 100%
- Zero total cost: percentage column shows 0% without NaN or divide-by-zero error

### Manual QA checklist

- [ ] Click the cost tile → popover opens
- [ ] Each row shows the correct model badge color
- [ ] Percentage column sums to ~100% (rounding may make it 99% or 101%)
- [ ] Click anywhere outside the tile → popover closes
- [ ] Press Escape → popover closes
- [ ] Switch time range → close popover, reopen → updated data shown

---

## Out of Scope

- Per-model trend over time (see Feature 5 for time-based breakdown)
- Clicking a model row to filter sessions by that model (follow-up feature)
- Exporting the breakdown table
- Weekly budget per model
