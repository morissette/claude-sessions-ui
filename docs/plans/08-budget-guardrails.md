# Feature 8: Budget Guardrails

**Phase:** 3 — Control | **Effort:** M | **Target:** Q4 2026

---

## Overview

Implement active budget enforcement by broadcasting budget status through the WebSocket and displaying a persistent red banner when any configured limit is exceeded. An optional file-based hook integration lets users wire the budget breach to a Claude `PreToolUse` hook that can pause sessions when the budget is hit.

**Prerequisite:** Feature 5 (Cost Trend Charts) must be implemented first — it introduces `~/.claude/claude-sessions-ui-config.json` and the `GET/PUT /api/config` endpoints that this feature reads.

---

## Problem / Motivation

Feature 5 lets users set a budget. Feature 8 makes that budget actionable. Without enforcement, a budget is just a display number. This feature closes the feedback loop: the user sets a limit, the dashboard monitors it in real time, and — optionally — Claude itself can be told to pause when the limit is hit.

---

## Acceptance Criteria

- [ ] When `daily_budget_usd` is set and `cost_today_usd >= daily_budget_usd`, a red banner appears above StatsBar
- [ ] When `weekly_budget_usd` is set and the 7-day rolling cost exceeds it, a red banner appears
- [ ] The banner specifies which limit was exceeded and by how much
- [ ] The banner is dismissible (close button), but reappears on the next WebSocket push if the budget is still exceeded
- [ ] The WebSocket payload includes a `budget_status` field on every push
- [ ] If no budgets are set, `budget_status` is `{"daily": null, "weekly": null}` — no banner
- [ ] Optionally: if `budget_exceeded.flag_path` is set in config, the backend writes `~/.claude/budget-exceeded.flag` when any budget is exceeded and removes it when spending returns below the limit

---

## Backend Changes

### `check_budget_status(stats, config)` — new function

```python
def check_budget_status(stats: dict, config: dict) -> dict:
    daily_limit  = config.get("daily_budget_usd")
    weekly_limit = config.get("weekly_budget_usd")

    daily_spent  = stats.get("cost_today_usd", 0.0)
    weekly_spent = stats.get("cost_week_usd",  0.0)   # see below

    def make_entry(limit, spent):
        if limit is None:
            return None
        return {
            "limit":    limit,
            "spent":    spent,
            "exceeded": spent >= limit,
            "pct":      round(spent / limit * 100, 1) if limit > 0 else 0,
        }

    return {
        "daily":  make_entry(daily_limit, daily_spent),
        "weekly": make_entry(weekly_limit, weekly_spent),
    }
```

### `cost_week_usd` addition to `compute_global_stats()`

`compute_global_stats()` currently computes `cost_today_usd`. Extend it to also compute `cost_week_usd` — the rolling 7-day cost:

```python
one_week_ago = now - timedelta(days=7)
cost_week_usd = sum(
    s["stats"]["estimated_cost_usd"]
    for s in sessions
    if s.get("last_active") and
       datetime.fromisoformat(s["last_active"]) >= one_week_ago
)
```

Add `"cost_week_usd": cost_week_usd` to the returned `stats` dict.

### WebSocket payload — add `budget_status`

In `websocket_endpoint()` (~line 1313 in `backend.py`), after computing `stats`:

```python
config = read_config()
budget_status = check_budget_status(stats, config)

# Optional: write/remove flag file
if config.get("budget_flag_path"):
    flag_path = Path(config["budget_flag_path"])
    any_exceeded = (
        (budget_status["daily"]  and budget_status["daily"]["exceeded"]) or
        (budget_status["weekly"] and budget_status["weekly"]["exceeded"])
    )
    if any_exceeded:
        flag_path.touch()
    elif flag_path.exists():
        flag_path.unlink()

await websocket.send_json({
    "sessions": sessions_data,
    "stats": stats,
    "savings": savings,
    "truncation": truncation,
    "budget_status": budget_status,
    "time_range": time_range,
})
```

### Config schema addition (Feature 5 config file)

The config schema gains one optional field:

```json
{
  "daily_budget_usd": 10.00,
  "weekly_budget_usd": 50.00,
  "budget_flag_path": "~/.claude/budget-exceeded.flag"
}
```

`budget_flag_path` is optional and defaults to `null`. When null, no flag file is written.

**Security:** `budget_flag_path` is resolved with `Path(path).expanduser().resolve()`. Restrict to paths within `~/.claude/` to prevent writing arbitrary files:

```python
def validate_flag_path(raw: str) -> Path | None:
    if not raw:
        return None
    p = Path(raw).expanduser().resolve()
    if not str(p).startswith(str(Path.home() / ".claude")):
        raise ValueError("budget_flag_path must be within ~/.claude/")
    return p
```

---

## Frontend Changes

### State addition in `App.jsx`

```javascript
const [budgetDismissed, setBudgetDismissed] = useState(false)
```

Reset `budgetDismissed` to `false` on each new WebSocket message (so the banner reappears if budget is still exceeded after manual close):

```javascript
// In onmessage handler, after setData(parsed):
setBudgetDismissed(false)
```

### Render `BudgetBanner` above StatsBar

```jsx
{!budgetDismissed && data?.budget_status && (
  <BudgetBanner
    status={data.budget_status}
    onDismiss={() => setBudgetDismissed(true)}
  />
)}
<StatsBar ... />
```

`BudgetBanner` only renders when at least one limit is exceeded:

```jsx
function BudgetBanner({ status, onDismiss }) {
  const exceeded = []
  if (status.daily?.exceeded)  exceeded.push(`daily ($${status.daily.spent.toFixed(2)} / $${status.daily.limit.toFixed(2)})`)
  if (status.weekly?.exceeded) exceeded.push(`weekly ($${status.weekly.spent.toFixed(2)} / $${status.weekly.limit.toFixed(2)})`)
  if (exceeded.length === 0) return null

  return (
    <div className="budget-banner" role="alert">
      <span className="budget-banner__icon">⚠</span>
      <span className="budget-banner__text">
        Budget exceeded: {exceeded.join(' and ')}
      </span>
      <button className="budget-banner__dismiss" onClick={onDismiss} aria-label="Dismiss">×</button>
    </div>
  )
}
```

### New component: `frontend/src/components/BudgetBanner.jsx`

Extract `BudgetBanner` to its own file for clarity. No breaking change — same props interface.

### New CSS: `frontend/src/components/BudgetBanner.css`

```css
.budget-banner {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.6rem 1rem;
  background: var(--color-error-bg, #fee2e2);
  border: 1px solid var(--color-error, #ef4444);
  border-radius: 6px;
  margin-bottom: 0.75rem;
  font-size: 0.875rem;
}
.budget-banner__icon { font-size: 1rem; }
.budget-banner__text { flex: 1; }
.budget-banner__dismiss {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 1.1rem;
  line-height: 1;
  color: var(--color-error);
}
```

---

## Hook Integration Documentation

Add a section to `README.md` explaining the optional hook integration:

```markdown
## Budget Guardrails with Claude Hooks

Set `budget_flag_path` in `~/.claude/claude-sessions-ui-config.json`:

```json
{
  "daily_budget_usd": 10.00,
  "budget_flag_path": "~/.claude/budget-exceeded.flag"
}
```

Then add a `PreToolUse` hook in your `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [{
      "matcher": ".*",
      "hooks": [{
        "type": "command",
        "command": "test ! -f ~/.claude/budget-exceeded.flag"
      }]
    }]
  }
}
```

When the dashboard detects a budget breach, it writes the flag file. The hook causes Claude to abort tool use until spending drops below the limit (or you delete the flag manually).
```

---

## Security Considerations

- **Flag file path:** `budget_flag_path` is validated to stay within `~/.claude/` — no writing to arbitrary system paths.
- **`PUT /api/config` with `budget_flag_path`:** The `validate_flag_path()` function is called server-side when saving config. A path like `"/etc/cron.d/evil"` returns a 400 error.
- **No shell execution:** the flag is written via `Path.touch()` — not via `subprocess` or `os.system`.
- **Race conditions:** `flag_path.unlink()` is wrapped in `try/except FileNotFoundError` to handle concurrent removals.

---

## Performance Considerations

- `check_budget_status()` is an O(1) dictionary lookup — no DB queries.
- `cost_week_usd` computation in `compute_global_stats()` is an O(n) pass already being made. Adding the 7-day sum is a single extra comprehension.
- `read_config()` is called on every WebSocket push cycle. Cache the config in memory with a 5-second TTL to avoid repeated disk reads:

```python
_config_cache: tuple[float, dict] | None = None

def read_config() -> dict:
    global _config_cache
    now = time.monotonic()
    if _config_cache and now - _config_cache[0] < 5:
        return _config_cache[1]
    data = _read_config_from_disk()
    _config_cache = (now, data)
    return data
```

---

## Testing Requirements

### Backend unit tests

- `test_check_budget_status_no_budgets`: `config = {}` → both entries are `null`
- `test_check_budget_status_daily_under`: `daily_budget=10, cost_today=5` → `exceeded=false, pct=50.0`
- `test_check_budget_status_daily_exceeded`: `daily_budget=10, cost_today=12` → `exceeded=true, pct=120.0`
- `test_check_budget_status_weekly`: weekly budget logic mirrors daily
- `test_flag_file_written_on_exceeded`: mock `flag_path.touch()`, verify called when exceeded
- `test_flag_file_removed_on_recovery`: flag exists, budget no longer exceeded → `unlink()` called
- `test_validate_flag_path_outside_claude_dir`: `"/etc/evil"` → raises `ValueError`
- `test_cost_week_usd_in_global_stats`: sessions from last 7 days + older session → only recent ones summed

### Frontend tests (Vitest)

- `BudgetBanner` renders nothing when no budget exceeded
- `BudgetBanner` renders for daily exceeded
- `BudgetBanner` renders for both exceeded simultaneously
- Dismiss button calls `onDismiss`
- Banner re-appears after WebSocket push (simulate new message → `budgetDismissed` resets)

### Manual QA checklist

- [ ] Set `daily_budget_usd` to $0.01 (guaranteed to be exceeded) → red banner appears
- [ ] Click "×" → banner disappears; next WebSocket push → banner reappears
- [ ] Clear budget (`PUT /api/config` with `null`) → banner gone on next push
- [ ] Set `budget_flag_path`, trigger breach → flag file created at expected path
- [ ] Spending drops below limit → flag file removed
- [ ] Test `budget_flag_path` with a path outside `~/.claude/` → 400 error from API

---

## Out of Scope

- Per-project budget limits
- Email or push notifications when budget is exceeded
- Automatically stopping Claude processes (the hook integration is opt-in and operates outside this app)
- Budget history / how often the budget has been exceeded
