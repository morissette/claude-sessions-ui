# Key References

## Pull Requests

| PR | Title | Status | Notes |
|----|-------|--------|-------|
| #1 | Add CLAUDE.md | Merged | Initial project documentation and memory |
| #2 | SQLite historical storage, time ranges, Docker | Merged | Core architecture: SQLite cache, time range routing, Dockerfile |
| #3 | Session detail overlay | Merged | Slide-in panel; `find_session_file`, `parse_session_detail` |
| #4 | Export session as skill | Merged | `GET /api/sessions/{id}/export-skill` |
| #5 | Merged #3 and #4 | Merged | Combined session detail + export |
| #6 | Transcript export, overlay UX redesign | Merged | `GET /api/sessions/{id}/transcript`, Markdown download |
| #7 | AI Assistant Dashboard roadmap | Merged | `ROADMAP.md`, untracked `frontend/dist/` |
| #8 | Slate design system | Merged | Light theme, cyan accent, `#f8fafc` backgrounds |
| #9 | Implementation plans for all 10 roadmap features | Merged | All plan docs live in `docs/plans/` |
| #10 | Per-model cost breakdown popover | Open | Feature 7 of roadmap |
| #11 | Persist filter/sort/time-range via localStorage | Merged | `PREFS_DEFAULTS` pattern |
| #12 | Unlimited history + custom date range | Merged | Feature 2 of roadmap |
| #13 | Project-level dashboard | Open | Feature 4; had 11 Copilot comments, complex rebase |
| #14 | Session analytics panel | Open | Feature 3 |
| #15 | Memory Explorer (read-only `~/.claude/` browser) | Open | Feature 6; security-critical |
| #16 | Full-text session search | Open | Feature 1 |
| #17 | Cost trend charts + budget alerts | Open | Feature 5 |

## Spec Documents

All feature plans are in `docs/plans/`:

- `docs/plans/README.md` — index with dependency graph for all 10 features
- `docs/plans/01-full-text-search.md` — FTS5 virtual table, parameterized queries
- `docs/plans/02-unlimited-history-date-range.md`
- `docs/plans/03-session-analytics-panel.md`
- `docs/plans/04-project-dashboard.md`
- `docs/plans/05-cost-trend-charts.md`
- `docs/plans/06-memory-explorer.md` — security-critical; path traversal validation pattern
- `docs/plans/07-per-model-cost-breakdown.md`
- `docs/plans/08-budget-guardrails.md`
- `docs/plans/09-batch-operations.md`
- `docs/plans/10-persistent-preferences.md`

## Infrastructure

- **LaunchAgent plist:** `~/Library/LaunchAgents/com.marie.claude-sessions-ui.plist` — runs `start.sh` on login with `KeepAlive`, logs to `~/.claude/claude-sessions-ui-launchd.log`
- **Prometheus target:** `Maries-Mac-mini.local:8765` (or current IP — check if DHCP changed)
- **Grafana:** `http://homelab2:3000` — provisioned dashboards in `grafana/dashboards/`, datasource config in `grafana/provisioning/`
