# Feature 4: Project-Level Dashboard

**Phase:** 1 — Depth | **Effort:** M | **Target:** Q2 2026

---

## Overview

Add a "Projects" view that groups sessions by project directory and displays aggregate stats per project. A top-level toolbar toggle switches between the existing "Sessions" list and the new "Projects" grid. Clicking a project card drills down to show only that project's sessions.

---

## Problem / Motivation

Power users work across many projects simultaneously. The current dashboard mixes all sessions together, making it hard to answer "How much have I spent on project X this month?" or "Which project is burning the most tokens?". A project-level view provides the project-centric perspective that team leads and cost-conscious developers need.

---

## Acceptance Criteria

- [ ] A "Sessions / Projects" toggle appears in the toolbar
- [ ] In "Projects" view, one card is shown per unique `project_name`
- [ ] Each project card shows: project name, session count, total cost, total tokens, models used, date of first and last session
- [ ] Clicking a project card switches to "Sessions" view filtered to that project
- [ ] A "×" button on the active project filter clears it and returns to unfiltered sessions
- [ ] The project filter persists across WebSocket reconnects for the current page session
- [ ] The `GET /api/projects` endpoint accepts the same `time_range` parameter as `GET /api/sessions`
- [ ] Projects are sorted by total cost descending by default
- [ ] An empty state is shown if no sessions exist for the selected time range

---

## Backend Changes

### New helper: `compute_project_stats(sessions: list[dict]) -> list[dict]`

Group sessions from the existing session list by `project_name`. Does not need a new DB query — operates on the already-fetched session list.

```python
def compute_project_stats(sessions: list[dict]) -> list[dict]:
    projects: dict[str, dict] = {}
    for s in sessions:
        name = s.get("project_name") or "unknown"
        path = s.get("project_path", "")
        if name not in projects:
            projects[name] = {
                "project_name": name,
                "project_path": path,
                "session_count": 0,
                "total_cost_usd": 0.0,
                "total_tokens": 0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "models": set(),
                "first_session": s.get("started_at"),
                "last_session": s.get("last_active"),
            }
        p = projects[name]
        p["session_count"] += 1
        stats = s.get("stats", {})
        p["total_cost_usd"]      += stats.get("estimated_cost_usd", 0.0)
        p["total_tokens"]        += stats.get("total_tokens", 0)
        p["total_input_tokens"]  += stats.get("input_tokens", 0)
        p["total_output_tokens"] += stats.get("output_tokens", 0)
        p["models"].add(s.get("model", "unknown"))
        if s.get("started_at") < p["first_session"]:
            p["first_session"] = s["started_at"]
        if s.get("last_active") > p["last_session"]:
            p["last_session"] = s["last_active"]

    for p in projects.values():
        p["models"] = sorted(p["models"])  # serialize set

    return sorted(projects.values(), key=lambda p: p["total_cost_usd"], reverse=True)
```

### New endpoint: `GET /api/projects`

```python
@app.get("/api/projects")
async def get_projects(time_range: str = "1d"):
    sessions = await get_sessions_for_range(time_range)
    return compute_project_stats(sessions)
```

Add in the HTTP endpoints section of `backend.py` (~line 1200).

### WebSocket `?project=` filter

Add optional `project` query parameter to the WebSocket endpoint:

```python
@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    time_range: str = "1d",
    project: str | None = None,
    ...
):
```

After fetching the session list, apply the project filter server-side before broadcasting:

```python
if project:
    sessions = [s for s in sessions if s.get("project_name") == project]
```

Filtering server-side means the full session list is never sent to the client unnecessarily.

---

## Frontend Changes

### New state in `App.jsx`

```javascript
const [viewMode, setViewMode] = useState('sessions')    // 'sessions' | 'projects'
const [selectedProject, setSelectedProject] = useState(null)
```

### WebSocket URL construction

When `selectedProject` is set, append `&project=` to the WebSocket URL:

```javascript
function buildWsUrl(timeRange, selectedProject) {
  let url = `ws://localhost:8765/ws?time_range=${timeRange}`
  if (selectedProject) url += `&project=${encodeURIComponent(selectedProject)}`
  return url
}
```

Reconnect when `selectedProject` changes.

### Toolbar toggle

```jsx
<div className="toolbar__view-toggle">
  <button
    className={`toolbar__view-btn ${viewMode === 'sessions' ? 'active' : ''}`}
    onClick={() => setViewMode('sessions')}
  >Sessions</button>
  <button
    className={`toolbar__view-btn ${viewMode === 'projects' ? 'active' : ''}`}
    onClick={() => setViewMode('projects')}
  >Projects</button>
</div>
```

### Active project filter badge

When `selectedProject` is set (regardless of `viewMode`), show a filter indicator near the toolbar:

```jsx
{selectedProject && (
  <span className="toolbar__project-filter">
    {selectedProject}
    <button onClick={() => setSelectedProject(null)}>×</button>
  </span>
)}
```

### Conditional rendering in main content area

```jsx
{viewMode === 'projects' && !selectedProject
  ? <ProjectList projects={projectData} onSelect={handleProjectSelect} />
  : <div className="session-list">...</div>
}
```

`projectData` is fetched separately from `GET /api/projects?time_range=...` (not through the WebSocket):

```javascript
const [projectData, setProjectData] = useState([])

useEffect(() => {
  if (viewMode !== 'projects') return
  fetch(`/api/projects?time_range=${timeRange}`)
    .then(r => r.json())
    .then(setProjectData)
}, [viewMode, timeRange])
```

### Project selection handler

```javascript
function handleProjectSelect(projectName) {
  setSelectedProject(projectName)
  setViewMode('sessions')   // drill down into sessions view
}
```

### New component: `frontend/src/components/ProjectCard.jsx`

Props:

```javascript
{
  project: {
    project_name: string,
    project_path: string,
    session_count: number,
    total_cost_usd: number,
    total_tokens: number,
    models: string[],
    first_session: string,
    last_session: string
  },
  onClick: () => void
}
```

Layout (similar to `SessionCard`):

```
[project_name]                    [total_cost]
[project_path (truncated)]        [session_count sessions]
[models badges]    [total_tokens]
[first–last date range]
```

### New CSS: `frontend/src/components/ProjectCard.css`

Reuse CSS custom properties (colors, spacing) from `SessionCard.css`. Card layout mirrors `SessionCard` structure for visual consistency.

---

## Security Considerations

- The `project` query parameter is URL-decoded server-side. Since it is used only as a string equality filter against in-memory session data (not in a SQL query), there is no injection risk. No path operations are performed on the value.
- `compute_project_stats` operates entirely on the already-validated session list — no filesystem access.

---

## Performance Considerations

- `compute_project_stats` is an O(n) pass over the session list — negligible for any realistic session count.
- `GET /api/projects` reuses the same session-fetching path as the WebSocket — no additional DB queries.
- The project list is fetched once on tab switch and on time range change. It is not pushed via WebSocket (projects change slowly).
- The WebSocket project filter happens server-side before serialization, so large session lists are not transmitted when a project filter is active.

---

## Testing Requirements

### Backend unit tests

- `test_compute_project_stats_groups_correctly`: sessions with 3 project names → 3 project dicts returned
- `test_compute_project_stats_cost_aggregation`: verify `total_cost_usd` = sum of individual session costs
- `test_compute_project_stats_model_dedup`: two sessions with same model → `models` contains one entry
- `test_compute_project_stats_date_range`: verify `first_session` = min started_at, `last_session` = max last_active
- `test_compute_project_stats_empty`: empty session list → empty result
- `test_projects_endpoint_200`: GET `/api/projects?time_range=1d` returns 200 with list

### Frontend tests (Vitest)

- `ProjectCard` renders all props correctly
- `handleProjectSelect` sets `selectedProject` and switches `viewMode` to "sessions"
- Project filter badge appears when `selectedProject !== null`
- "×" button clears `selectedProject`

### Manual QA checklist

- [ ] Click "Projects" → project cards appear grouped correctly
- [ ] Project cards show correct session counts and costs (verify against Sessions view totals)
- [ ] Click a project card → view switches to Sessions filtered to that project
- [ ] Active project badge visible in toolbar
- [ ] Click "×" on badge → all sessions return
- [ ] Switch time range while in Projects view → project stats update
- [ ] Project with a very long path name → path truncated, card layout not broken

---

## Out of Scope

- Editing or renaming project names
- Per-project budget limits (that is Feature 8)
- Nested sub-project groupings
- Drag-and-drop session reassignment between projects
