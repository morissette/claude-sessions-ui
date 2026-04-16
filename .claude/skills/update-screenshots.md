---
name: update-screenshots
description: Takes fresh screenshots of claude-sessions-ui features and updates FEATURES.md image references. Run before opening a PR or after UI changes. Requires dev server running on :5173 (./dev.sh).
---

# update-screenshots

Captures up-to-date screenshots of the claude-sessions-ui UI and updates FEATURES.md.

## When to invoke

- Before opening a PR that changes UI components or adds a new view/tab
- After merging a visual bug fix
- When explicitly asked to refresh the feature gallery

## Steps

### 1. Verify dev server is up

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:5173
```

If not 200, tell the user to run `./dev.sh` and wait for it to be ready. Do not proceed without a live server.

### 2. Identify what changed

Check which UI files changed relative to main:

```bash
git diff --name-only origin/main...HEAD -- 'frontend/src/**' '*.css' '*.jsx'
```

Cross-reference with FEATURES.md to find:
- Sections whose screenshots are stale (touch a changed component)
- New sections that need screenshots (new component/tab referenced in FEATURES.md but `images/` file missing)

### 3. Decide which screenshots to take

Rules:
- Always re-shoot any section whose component file was modified.
- Always shoot any FEATURES.md section referencing a non-existent `images/` file.
- Skip sections whose component is unchanged AND whose image exists.
- For a new top-level tab/view (e.g. Analytics), take at minimum: one full-tab overview screenshot + one scrolled screenshot showing lower content.

### 4. Take screenshots using browser-qa-agent

Spawn a browser-qa-agent with instructions like:

> Navigate to http://localhost:5173. For each of the following screenshots, perform the steps listed and save the file to the exact path given. Report back what you saw in each view.
>
> [List each screenshot: view to navigate to, UI state to set up (tab click, filter, hover), file path]

File naming convention: `images/feature-<kebab-description>.png`

Use the existing names in `images/` as reference — do not rename files that already exist and are referenced in FEATURES.md.

### 5. Update FEATURES.md

After browser-qa-agent confirms files saved:
- Add new `![caption](images/feature-name.png)` lines for newly added screenshots
- Remove references to screenshots that were deleted
- Keep section prose accurate (update metric names, section titles, feature descriptions to match current UI)
- Do NOT change the overall document structure unless a section was completely removed

### 6. Commit

Stage only `images/` and `FEATURES.md`:

```bash
git add images/ FEATURES.md
git commit -m "docs: refresh screenshots for <brief description of change>"
```

## Screenshot inventory (current)

The following screenshots exist and their FEATURES.md sections:

| Image file | Section |
|---|---|
| `feature-dashboard-overview.png` | Dashboard Overview |
| `feature-stats-bar.png` | Stats Bar |
| `feature-stats-cost-expanded.png` | Stats Bar (cost drilldown) |
| `feature-budget-guardrails-banner.png` | Budget Guardrails |
| `feature-filter-controls.png` | Session Filtering & Sorting |
| `feature-filter-active.png` | Session Filtering — Active |
| `feature-filter-today.png` | Session Filtering — Today |
| `feature-sort-by-cost.png` | Session Filtering — Sort by cost |
| `feature-sort-by-turns.png` | Session Filtering — Sort by turns |
| `feature-time-range-1h.png` | Time Ranges |
| `feature-time-range-3d.png` | Time Ranges |
| `feature-time-range-1m.png` | Time Ranges |
| `feature-time-range-6m.png` | Time Ranges |
| `feature-time-range-custom.png` | Time Ranges — custom picker |
| `feature-search-sessions-view.png` | Full-Text Search |
| `feature-search-projects-view.png` | Full-Text Search |
| `feature-active-session-card.png` | Session Cards |
| `feature-session-card-with-summary.png` | Session Cards — with summary |
| `feature-session-card-hover.png` | Session Cards — hover |
| `feature-session-detail-overlay.png` | Session Detail & Transcript |
| `feature-session-detail-transcript.png` | Session Detail & Transcript |
| `feature-session-detail-header.png` | Session Detail — header |
| `feature-session-detail-overlay-scrolled.png` | Session Detail — scrolled |
| `feature-session-detail-export-skill.png` | Export as Skill |
| `feature-session-detail-analytics.png` | Session Analytics (per-session) |
| `feature-session-analytics-charts.png` | Session Analytics charts |
| `feature-cost-trends-chart.png` | Cost Trends Chart |
| `feature-batch-select-mode.png` | Batch Operations |
| `feature-batch-selected-sessions.png` | Batch Operations — selected |
| `feature-batch-operations-toolbar.png` | Batch Operations — toolbar |
| `feature-ollama-summarize-loading.png` | AI Session Summaries |
| `feature-ollama-summarize-result.png` | AI Session Summaries |
| `feature-savings-banner.png` | Savings Analytics |
| `feature-savings-banner-detail.png` | Savings Analytics — detail |
| `feature-memory-view.png` | Memory View |
| `feature-memory-view-file-selected.png` | Memory View — file selected |
| `feature-websocket-live-indicator.png` | Live WebSocket Indicator |
| `feature-analytics-tab.png` | Analytics Dashboard — overview |
| `feature-analytics-charts.png` | Analytics Dashboard — charts & memory pane |

## Notes

- Screenshots are taken with whatever data is in the user's live `~/.claude/` directory — they will show real session names and costs. That is intentional and expected.
- If the dev server is on a different port (configured via `DEV_PORT` or similar), adjust the URL accordingly.
- Do not fabricate screenshots. If the browser-qa-agent cannot reach the app or fails to save a file, report the failure rather than skipping silently.
