# Refactor Plan: Modularize `backend.py` + Python 3.14 Upgrade

## Context

`backend.py` is a 2,213-line monolith with 15 logical sections, 17 FastAPI routes, 1 WebSocket endpoint, and a full SQLite/FTS5/Ollama/Prometheus stack. As the codebase grows, a single file creates friction: long search times, wide PR diffs, hard-to-isolate test failures, and difficulty adding features without touching unrelated code.

`tests/test_backend.py` mirrors the monolith at 1,121 lines with 16 test classes and 10 standalone functions.

Python is currently pinned to 3.11. Four deprecated `asyncio.get_event_loop()` calls exist and must be fixed before 3.14 enforces the change. Everything else (typing, datetime, union syntax) is already 3.9+-compliant.

**Goal:** Zero behavior change. All 50+ existing tests pass without logic modification. New module structure is composable, independently importable, and testable in isolation.

---

## Critical Files

| File | Role |
|------|------|
| `backend.py` | Source of truth — every line must be accounted for |
| `tests/test_backend.py` | Defines the full public API surface; must keep passing |
| `pyproject.toml` | `pythonpath`, ruff `target-version`, pytest config |
| `Dockerfile` | Base image + CMD; must update for package layout |
| `dev.sh` / `start.sh` | Entry points; must update uvicorn path |
| `.github/workflows/lint.yml` | Ruff target — changes from `backend.py` to `backend/` |
| `.github/workflows/test.yml` | Python version pin |

---

## Target Package Structure

```
backend/
├── __init__.py          # Backwards-compat shim: __getattr__/__setattr__ proxy
├── app.py               # FastAPI instance, CORS, lifespan (startup/shutdown)
├── config.py            # read_config, write_config, _config_cache
├── constants.py         # All paths, MODEL_PRICING, TIME_RANGE_HOURS, etc.
├── database.py          # SQLite: init_db, upsert, queries, background tasks
│                        #   Also holds: _extract_messages_from_jsonl, _sync_fts
├── fts.py               # backfill_fts, search_fts, search_jsonl_live
├── metrics.py           # Prometheus gauge defs + _update_prometheus
├── ollama.py            # Ollama integration + savings calculations
├── parsing.py           # parse_session_file, get_session_cwd, _session_cache
├── aggregation.py       # get_all_sessions, compute_global_stats, compute_project_stats
├── process.py           # get_running_claude_processes
├── detail.py            # find_session_file, parse_session_detail, parse_session_analytics
├── skills.py            # slugify, extract, resolve, ollama/template generate
├── memory.py            # validate_memory_path, tree helpers
├── routes/
│   ├── __init__.py      # register_routes(app) — includes all routers
│   ├── sessions.py      # /api/sessions, /api/search, /api/{id}/* (7 endpoints)
│   ├── projects.py      # /api/projects, /api/trends
│   ├── config.py        # /api/config GET/PUT
│   ├── memory.py        # /api/memory, /api/memory/file
│   ├── system.py        # /api/db/status, /api/ollama, /metrics
│   └── websocket.py     # /ws WebSocket endpoint
└── main.py              # Entry point: configure logging, uvicorn.run
```

---

## Dependency DAG (no cycles allowed)

```
constants   (leaf — no backend imports)
config      → constants
metrics     → (prometheus_client only)
process     → (psutil only)
parsing     → constants
ollama      → constants
memory      → constants
skills      → constants
detail      → constants, parsing (_analytics_cache)
database    → constants, detail (find_session_file), ollama (get_cached_summary),
              process (get_running_claude_processes)
              [_sync_fts + _extract_messages_from_jsonl live IN database to break cycle]
fts         → constants, database (_db_conn, _db_lock, _extract_messages_from_jsonl)
aggregation → constants, parsing, process, ollama, database, metrics
routes/*    → everything above
app         → database (init_db, backfill_daily_costs), fts (backfill_fts), routes
main        → app
```

**Key circular-import solutions:**
- `_sync_fts` and `_extract_messages_from_jsonl` move INTO `database.py` — breaks the database↔fts cycle
- `_startup_backfill` moves into `app.py` lifespan — calls both `database` and `fts`, fine from app layer
- `fts.py` imports from `database` only (one direction)

---

## Backwards Compatibility: `import backend` Zero-Change Strategy

Tests use `monkeypatch.setattr(backend, "CLAUDE_DIR", tmp_path)`. For this to reach the owning module, `backend/__init__.py` uses a **`_PatchableModule`** metaclass trick:

```python
# backend/__init__.py
import importlib, sys

_SUBMODULE_MAP = {
    "CLAUDE_DIR":        ("constants", "CLAUDE_DIR"),
    "DB_PATH":           ("constants", "DB_PATH"),
    "_session_cache":    ("parsing",   "_session_cache"),
    "_db_conn":          ("database",  "_db_conn"),
    # ... all 30+ symbols tests touch
}

def __getattr__(name):
    if name in _SUBMODULE_MAP:
        mod_name, attr = _SUBMODULE_MAP[name]
        return getattr(importlib.import_module(f"backend.{mod_name}"), attr)
    raise AttributeError(name)

class _PatchableModule(type(sys.modules[__name__])):
    def __setattr__(self, name, value):
        if name in _SUBMODULE_MAP:
            mod_name, attr = _SUBMODULE_MAP[name]
            setattr(importlib.import_module(f"backend.{mod_name}"), attr, value)
            return
        super().__setattr__(name, value)

sys.modules[__name__].__class__ = _PatchableModule
```

**Internal convention:** All modules access constants via `constants.ATTR` (attribute access on module object), NOT `from backend.constants import ATTR` (local binding that won't see monkeypatches).

**Fallback (Option B):** If the proxy doesn't satisfy all test cases, mechanically update monkeypatch targets: `backend.CLAUDE_DIR` → `backend.constants.CLAUDE_DIR`.

---

## Phase Sequence

### Phase 0 — Baseline (no code changes)

```bash
git checkout -b refactor/modularize-backend
pytest tests/ -v   # record passing test count
ruff check backend.py
```

---

### Phase 1 — Leaf Modules (no backend deps)

**Create:** `backend/constants.py`, `backend/config.py`, `backend/__init__.py`, `backend/app.py`, `backend/main.py`

`constants.py` moves from `backend.py` lines 70–158:
- All path constants: `CLAUDE_DIR`, `DB_PATH`, `LIVE_HOURS`, `TIME_RANGE_HOURS`, `SUMMARIES_DIR`, `SKILLS_DIR`, `SAVINGS_FILE`, `TRUNCATION_SAVINGS_FILE`, `OLLAMA_URL`, `SUMMARY_MODEL`, `CONFIG_PATH`, `CLAUDE_BASE_DIR`, `MEMORY_ALLOWLIST`, `MEMORY_ALLOWLIST_FILES`, `SUMMARY_COST_ESTIMATE_USD`, `MODEL_PRICING`
- `_normalize_ts()` utility (line 189 — no deps)

`config.py` moves lines 97–124: `_config_cache`, `_read_config_from_disk`, `read_config`, `write_config`

`app.py`: FastAPI instance + CORS middleware (lifespan stub, completed in Phase 3)

`main.py`: Moves `if __name__ == "__main__"` block (lines 2186–2213)

**Gate:** `python -c "from backend.constants import MODEL_PRICING"` ✓
**Commit:** `refactor(phase1): extract constants, config, app, main into backend/ package`

---

### Phase 2 — Pure Logic Modules

**Create:** `backend/process.py`, `backend/parsing.py`, `backend/metrics.py`, `backend/ollama.py`, `backend/memory.py`, `backend/skills.py`, `backend/detail.py`

| Module | Source lines | Key contents |
|--------|-------------|--------------|
| `process.py` | 724–750 | `get_running_claude_processes` |
| `parsing.py` | 755–936 | `_session_cache`, `_cwd_cache`, `get_session_cwd`, `parse_session_file` |
| `metrics.py` | 31–42, 1114–1124 | Prometheus gauge defs (moved from top of backend.py), `_update_prometheus` |
| `ollama.py` | 1127–1250 | All Ollama functions + `compute_truncation_savings`, `compute_ollama_savings` |
| `memory.py` | 1660–1700 | `validate_memory_path` |
| `skills.py` | 1537–1655 | `slugify_skill_name`, `extract_session_skill_data`, `resolve_skill_path`, `ollama_generate_skill`, `template_generate_skill` |
| `detail.py` | 1255–1533 | `_analytics_cache`, `find_session_file`, `parse_session_detail`, `parse_session_analytics`, `render_transcript` |

**Gate:** All new modules importable without error; `ruff check backend/` clean
**Commit:** `refactor(phase2): extract pure-logic modules`

---

### Phase 3 — Database + FTS + Lifespan

**Create:** `backend/database.py`, `backend/fts.py`
**Modify:** `backend/app.py` (add full lifespan)

`database.py` moves lines 160–536 **plus** `_extract_messages_from_jsonl` (line 541) and `_sync_fts` (line 572):
- `_db_conn`, `_db_lock` module state
- `get_db()`, `init_db()`, `upsert_sessions_to_db()`
- `get_sessions_from_db()`, `get_sessions_for_range()`, `get_all_sessions_unbounded()`, `get_session_by_id()`
- `_upsert_in_background()`, `backfill_daily_costs()`
- `_extract_messages_from_jsonl()`, `_sync_fts()` ← moved here to prevent cycle

`fts.py` moves lines 583–719: `_fts_backfill_running`, `backfill_fts`, `search_fts`, `search_jsonl_live`

`app.py` lifespan: moves `_startup_backfill` logic here; calls `init_db()`, `backfill_daily_costs()`, `backfill_fts()`.

**Gate:** `python -c "from backend.database import init_db; from backend.fts import search_fts"` — no circular import
**Commit:** `refactor(phase3): extract database and fts, wire lifespan`

---

### Phase 4 — Aggregation Module

**Create:** `backend/aggregation.py`

Moves lines 938–1125: `_norm_ts`, `compute_project_stats`, `get_all_sessions`, `compute_global_stats`, `get_sessions_for_range` (dispatcher calling both `get_all_sessions` and `get_sessions_from_db`).

**Gate:** `python -c "from backend.aggregation import compute_global_stats"` ✓
**Commit:** `refactor(phase4): extract aggregation module`

---

### Phase 5 — Routes Subpackage

**Create:** `backend/routes/__init__.py` + 6 route files using `APIRouter`

`routes/__init__.py` exports `register_routes(app)` which calls `app.include_router(...)` for all routers.

| Route file | Endpoints |
|-----------|-----------|
| `sessions.py` | `GET /api/sessions`, `GET /api/search`, `POST /api/{id}/summarize`, `GET /api/{id}/detail`, `GET /api/{id}/transcript`, `GET /api/{id}/analytics`, `POST /api/{id}/export-skill` |
| `projects.py` | `GET /api/projects`, `GET /api/trends` |
| `config.py` | `GET/PUT /api/config` |
| `memory.py` | `GET /api/memory`, `GET /api/memory/file` |
| `system.py` | `GET /api/db/status`, `GET /api/ollama`, `GET /metrics` |
| `websocket.py` | `WebSocket /ws` + `_active_ws` module state |

**Critical:** Static file mount in `app.py` must come **after** `register_routes(app)`.

`backend/__init__.py` — finalize `_SUBMODULE_MAP` with all symbols tests access:

```
CLAUDE_DIR, DB_PATH, SUMMARIES_DIR, SAVINGS_FILE, TRUNCATION_SAVINGS_FILE, SKILLS_DIR,
CONFIG_PATH, MODEL_PRICING, TIME_RANGE_HOURS, _session_cache, _cwd_cache, _db_conn,
_config_cache, app, parse_session_file, get_session_cwd, compute_global_stats,
compute_project_stats, get_sessions_for_range, get_sessions_from_db, init_db,
upsert_sessions_to_db, find_session_file, parse_session_detail, slugify_skill_name,
extract_session_skill_data, resolve_skill_path, template_generate_skill,
compute_truncation_savings, compute_ollama_savings, get_cached_summary, cache_summary,
validate_memory_path, _read_config_from_disk, get_all_sessions,
get_running_claude_processes, ollama_is_available, check_budget_status, validate_flag_path
```

**Gate:** `python -m backend.main` starts; `curl :8765/api/sessions` returns JSON
**Commit:** `refactor(phase5): extract routes into backend/routes/ subpackage`

---

### Phase 6 — Delete Monolith + Infrastructure Updates

**Delete:** `backend.py`

Infrastructure changes:

```diff
# Dockerfile
- FROM python:3.11-slim
+ FROM python:3.14-slim
- COPY backend.py ./
+ COPY backend/ ./backend/
- CMD ["python3", "backend.py"]
+ CMD ["python3", "-m", "backend.main"]

# dev.sh
- python3 -m uvicorn backend:app ... --reload
+ python3 -m uvicorn backend.app:app ... --reload

# start.sh
- python3 backend.py
+ python3 -m backend.main

# .github/workflows/lint.yml
- ruff check ... backend.py
+ ruff check ... backend/
```

Update `CLAUDE.md`: remove "Keep `backend.py` as a single file" convention, document new package structure.

**Gate:** `pytest tests/ -v` — ALL pass (same count as Phase 0); `ruff check backend/` clean
**Commit:** `refactor(phase6): remove backend.py monolith, update infrastructure`

---

### Phase 7 — Python 3.14 Upgrade

Fix 4 deprecated `asyncio.get_event_loop()` → `asyncio.get_running_loop()`:

| File | Function | Original line |
|------|----------|--------------|
| `backend/fts.py` | `backfill_fts()` | 610 |
| `backend/fts.py` | `search_fts()` | 649 |
| `backend/fts.py` | `search_jsonl_live()` | 719 |
| `backend/detail.py` | `parse_session_analytics()` | 1529 |

Version bumps:
- `Pipfile`: `python_version = "3.11"` → `"3.14"`
- `Dockerfile`: `python:3.11-slim` → `python:3.14-slim`
- `pyproject.toml`: `target-version = "py311"` → `"py314"` (or `"py313"` if ruff doesn't yet support py314)
- `.github/workflows/test.yml`: `python-version: "3.11"` → `"3.14"`
- Run `pipenv lock` to regenerate lockfile

**Gate:** No `DeprecationWarning` for `get_event_loop`; `pytest tests/ -v` passes
**Commit:** `chore(phase7): upgrade to Python 3.14, fix deprecated asyncio calls`

---

### Phase 8 — Split Test File

Split `tests/test_backend.py` into per-module files. Move shared helpers to `tests/conftest.py`.

| New file | Source test classes |
|----------|---------------------|
| `tests/test_constants.py` | `TestModelPricing` |
| `tests/test_parsing.py` | `TestGetSessionCwd`, `TestParseSessionFile` |
| `tests/test_aggregation.py` | `TestComputeGlobalStats`, `TestComputeGlobalStatsWithRange`, `test_compute_project_stats_*` |
| `tests/test_ollama.py` | `TestComputeTruncationSavings`, `TestComputeOllamaSavings`, `TestSummaryCache` |
| `tests/test_database.py` | `TestSQLiteInit`, `TestUpsertSessions`, `TestGetSessionsFromDb`, `TestGetSessionsForRange` |
| `tests/test_detail.py` | `TestSessionDetail`, `test_analytics_*` |
| `tests/test_skills.py` | `TestExportSkill` |
| `tests/test_memory.py` | `TestValidateMemoryPath` |
| `tests/test_config.py` | `test_read_config_*`, `test_put_config_*` |
| `tests/test_routes.py` | `TestApiEndpoints`, `test_search_*`, `test_get_trends_*`, `test_api_projects_*`, budget/batch tests |

**Gate:** Each file runs independently; delete `tests/test_backend.py` only after all pass
**Commit:** `test(phase8): split test_backend.py into per-module test files`

---

## Risk Registry

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| `database` ↔ `fts` circular import | Medium | Build fails | `_sync_fts` + `_extract_messages_from_jsonl` live in `database.py` |
| `monkeypatch.setattr(backend, X)` misses owning module | High | Tests fail | `_PatchableModule.__setattr__` proxy; fallback: update 16 monkeypatch targets |
| `from backend.constants import X` creates frozen local bindings | High | Silent patch misses | Convention: always `constants.X` not `from backend.constants import X` |
| Module-level side effects at import | Medium | ImportError in tests | Move to lifespan startup hook |
| `python:3.14-slim` not on DockerHub | Low | Docker build fails | Use `python:3.14-rc-slim` |
| Ruff `target-version = "py314"` unsupported | Medium | Lint fails | Use `"py313"` — functionally identical |
| Static mount must be last router | Low | API 404s | Ensure `register_routes(app)` precedes `app.mount("/", ...)` |

---

## End-to-End Verification Checklist (after Phase 6)

- [ ] `pytest tests/ -v` — same count as Phase 0, all pass
- [ ] `ruff check backend/` — no errors
- [ ] `python -m backend.main` — starts on :8765
- [ ] `./dev.sh` — hot reload works on :5173/:8765
- [ ] `curl http://localhost:8765/api/sessions` → JSON
- [ ] WebSocket `/ws` connects
- [ ] `./docker.sh build && ./docker.sh up` — container serves on :8765
- [ ] `import backend; backend.CLAUDE_DIR` → correct path (proxy works)
