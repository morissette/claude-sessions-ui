# CLAUDE.md

## Project Overview

Claude Sessions UI is a real-time monitoring dashboard for Claude CLI sessions. It reads JSONL session files from `~/.claude/projects/`, parses token usage and costs, and streams live updates via WebSocket. An optional local Ollama integration generates session summaries and tracks cost savings vs. the Claude API.

## Architecture

Single-file Python backend (`backend.py`) + React/Vite frontend (`frontend/src`). No database — state is derived by parsing JSONL files on each request, with mtime-based caching. All configuration is hardcoded constants at the top of `backend.py` (no `.env` file).

```
~/.claude/projects/{project}/{session_id}.jsonl  → parsed by backend.py
~/.claude/session_summaries/                     → Ollama summary cache
~/.claude/claude-sessions-ui.log                 → runtime logs
```

**Data flow:** Browser WebSocket → FastAPI `/ws` → JSONL parsing → token/cost calculation → Prometheus metrics update → JSON response.

## Commands

### Development
```bash
./dev.sh          # Hot reload: Vite on :5173, FastAPI on :8765
```

### Production
```bash
./start.sh        # Build frontend, serve everything from FastAPI on :8765
```

### Testing
```bash
pytest tests/ -v                          # Backend unit tests
cd frontend && npm test                   # Frontend tests (Vitest)
```

### Linting
```bash
ruff check backend.py                     # Python lint
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
| `backend.py` | All Python logic: FastAPI app, JSONL parsing, cost calc, WebSocket, Ollama, Prometheus |
| `frontend/src/App.jsx` | Root component, WebSocket client, filter/sort state |
| `frontend/src/components/SessionCard.jsx` | Per-session display, summary trigger |
| `frontend/src/components/StatsBar.jsx` | Aggregate stats across all sessions |
| `frontend/src/components/SavingsBanner.jsx` | Ollama savings display |
| `tests/test_backend.py` | pytest unit tests for backend functions |

## Backend Architecture Notes

- **`MODEL_PRICING`** dict at top of `backend.py` — rates per million tokens. Update here when new models launch.
- **Caching**: `_session_cache` and `_cwd_cache` are module-level dicts keyed by file path + mtime. Don't add database-style persistence.
- **Process discovery**: Uses `psutil` to match active Claude processes. Checks `--resume` flag first, falls back to CWD matching.
- **Ollama**: All calls are wrapped in try/except — the app degrades gracefully if Ollama is unavailable. Never make Ollama required.
- **Sections in backend.py** are delimited by comment dividers (`# ─── Section ───`). Keep this convention.

## Frontend Architecture Notes

- Pure hooks (no class components, no state management library like Redux/Zustand).
- WebSocket auto-reconnects with 3-second retry. Connection state drives UI indicators.
- Helper formatters (`fmt`, `fmtCost`, `timeAgo`, `modelShort`) live in `App.jsx` — don't duplicate them in components.
- CSS uses BEM-like naming. No CSS-in-JS, no Tailwind — plain CSS files per component.

## CI/CD

GitHub Actions on every push/PR:
- **lint.yml**: Ruff (`backend.py`) + ESLint (`frontend/src`) with reviewdog PR comments
- **test.yml**: pytest + Vitest

Both must pass before merge. Ruff is strict (rules: E, W, F, I, UP, B, C4, SIM), line length 100.

## Conventions

- Keep `backend.py` as a single file. Don't split into modules unless it grows beyond ~1000 lines.
- No TypeScript — plain JavaScript throughout.
- No ORM, no database. File-based state only.
- Ollama features must always degrade gracefully.
- When adding new Claude models, add them to `MODEL_PRICING` in `backend.py` and add a test in `tests/test_backend.py`.
- Run `ruff check` and `pytest` locally before pushing — CI will reject failures.
