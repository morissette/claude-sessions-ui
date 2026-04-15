# CLAUDE.md

## Project Overview

Claude Sessions UI is a real-time monitoring dashboard for Claude CLI sessions. It reads JSONL session files from `~/.claude/projects/`, parses token usage and costs, and streams live updates via WebSocket. An optional local Ollama integration generates session summaries and tracks cost savings vs. the Claude API.

## Architecture

Python backend package (`backend/`) + React/Vite frontend (`frontend/src`). State is derived by parsing JSONL files on each request (mtime-based caching) for short time ranges (≤24h), and from a SQLite DB for historical ranges (3d–6m). All configuration is hardcoded constants in `backend/constants.py` (no `.env` file), except `OLLAMA_URL` which can be overridden via environment variable.

```
~/.claude/projects/{project}/{session_id}.jsonl  → parsed by backend/parsing.py
~/.claude/claude-sessions-ui.db                  → SQLite historical store
~/.claude/session_summaries/                     → Ollama summary cache
~/.claude/claude-sessions-ui.log                 → runtime logs
```

**Data flow:** Browser WebSocket (`?time_range=1d`) → FastAPI `/ws` → JSONL parsing (short ranges) or SQLite query (long ranges) → token/cost calculation → Prometheus metrics update → JSON response.

**Time range routing:**
- `1h`, `1d` → JSONL parsing (live, fast path)
- `3d`, `1w`, `2w`, `1m`, `6m` → SQLite query (historical, pre-indexed)

## Commands

### Development
```bash
./dev.sh          # Hot reload: Vite on :5173, FastAPI on :8765
```

### Production
```bash
./start.sh        # Build frontend, serve everything from FastAPI on :8765
```

### Docker
```bash
./docker.sh build   # Build the Docker image
./docker.sh up      # Start container at http://localhost:8765
./docker.sh down    # Stop container
./docker.sh logs    # Tail container logs
```

### Testing
```bash
pytest tests/ -v                          # Backend unit tests
cd frontend && npm test                   # Frontend tests (Vitest)
```

### Linting
```bash
ruff check backend/                       # Python lint
cd frontend && npm run lint               # JS lint (ESLint)
cd frontend && npm run lint:fix           # Auto-fix JS
```

### Install dependencies
```bash
pipenv install                            # Python
cd frontend && npm install                # Node
```

## Key Files

| File | Purpose |
|------|---------|
| `backend/__init__.py` | Package entry point; re-exports key symbols for import compatibility |
| `backend/constants.py` | `MODEL_PRICING`, `TIME_RANGE_HOURS`, `LIVE_HOURS`, paths — all hardcoded config |
| `backend/app.py` | FastAPI app factory, lifespan (startup backfill, DB init) |
| `backend/main.py` | `uvicorn.run` entry point (`python -m backend.main`) |
| `backend/parsing.py` | JSONL parsing, token/cost calculation, mtime-based caching |
| `backend/database.py` | SQLite schema, upsert, historical queries |
| `backend/fts.py` | Full-text search helpers |
| `backend/aggregation.py` | Cross-session aggregation and stats |
| `backend/process.py` | `psutil`-based active Claude process discovery |
| `backend/ollama.py` | Ollama summary generation (always degrades gracefully) |
| `backend/metrics.py` | Prometheus metrics |
| `backend/memory.py` | Session memory helpers |
| `backend/skills.py` | Skills-related helpers |
| `backend/detail.py` | Per-session detail helpers |
| `backend/routes/` | FastAPI routers (WebSocket, REST endpoints) |
| `frontend/src/App.jsx` | Root component, WebSocket client, filter/sort/time-range state |
| `frontend/src/components/SessionCard.jsx` | Per-session display, summary trigger |
| `frontend/src/components/StatsBar.jsx` | Aggregate stats across all sessions |
| `frontend/src/components/SavingsBanner.jsx` | Ollama savings display |
| `tests/test_backend.py` | pytest unit tests for backend functions |
| `Dockerfile` | Multi-stage build (Node → Python) |
| `docker-compose.yml` | Single service; mounts `~/.claude/` as volume |
| `docker.sh` | Convenience wrapper: `build`, `up`, `down`, `logs` |

## Backend Architecture Notes

- **`MODEL_PRICING`** in `backend/constants.py` — rates per million tokens. Update here when new models launch.
- **`DB_PATH`**: `~/.claude/claude-sessions-ui.db` — SQLite historical store. The DB is a cache; delete and restart to rebuild from JSONL.
- **`LIVE_HOURS = 24`**: time ranges ≤ this use JSONL; longer ranges use SQLite. Startup backfill populates SQLite from all JSONL history asynchronously.
- **`TIME_RANGE_HOURS`**: dict mapping `"1h"/"1d"/"3d"/"1w"/"2w"/"1m"/"6m"` → hours. Add new ranges here + in the frontend `TIME_RANGES` array.
- **Caching**: `_session_cache` and `_cwd_cache` are module-level dicts keyed by file path + mtime. SQLite upserts happen in a thread pool (fire-and-forget in the WS loop).
- **Process discovery**: Uses `psutil` to match active Claude processes. Checks `--resume` flag first, falls back to CWD matching (JSONL path only; SQLite path uses `--resume` match only).
- **Ollama**: All calls are wrapped in try/except — the app degrades gracefully if Ollama is unavailable. Never make Ollama required. `OLLAMA_URL` reads from `os.environ` (default `http://localhost:11434`) so Docker can point it at the host.
- **Sections in each module** are delimited by comment dividers (`# ─── Section ───`). Keep this convention.

## Frontend Architecture Notes

- Pure hooks (no class components, no state management library like Redux/Zustand).
- WebSocket auto-reconnects with 3-second retry. Connection state drives UI indicators.
- Helper formatters (`fmt`, `fmtCost`, `timeAgo`, `modelShort`) live in `App.jsx` — don't duplicate them in components.
- CSS uses BEM-like naming. No CSS-in-JS, no Tailwind — plain CSS files per component.

## CI/CD

GitHub Actions on every push/PR:
- **lint.yml**: Ruff (`backend/`) + ESLint (`frontend/src`) with reviewdog PR comments
- **test.yml**: pytest + Vitest

Both must pass before merge. Ruff is strict (rules: E, W, F, I, UP, B, C4, SIM), line length 100.

## Conventions

- No TypeScript — plain JavaScript throughout.
- No ORM. SQLite is the only persistence layer and is a derived cache — never the source of truth.
- Ollama features must always degrade gracefully.
- When adding new Claude models, add them to `MODEL_PRICING` in `backend/constants.py` and add a test in `tests/test_constants.py`.
- When adding new time ranges, update `TIME_RANGE_HOURS` in `backend/constants.py` AND `TIME_RANGES` in `frontend/src/App.jsx`.
- Run `ruff check` and `pytest` locally before pushing — CI will reject failures.
