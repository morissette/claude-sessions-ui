# Architectural & Design Decisions

## Backend

### Single-file backend (`backend.py`)
All Python logic lives in one file (~700+ lines). Intentional — resist splitting into modules unless it grows beyond ~1000 lines. Sections are delimited by `# ─── Section ───` comment dividers; keep this convention.

### No `.env` file — hardcoded constants
All configuration is hardcoded at the top of `backend.py`. No dotenv, no config file. Only `OLLAMA_URL` reads from `os.environ` (so Docker can override it).

### SQLite is a derived cache, not the source of truth
`~/.claude/claude-sessions-ui.db` is rebuilt from JSONL on startup. Safe to delete and restart to rebuild. Never treat it as the primary data store.

### Time range routing: JSONL vs SQLite
- `1h`, `1d` → JSONL parsing (live fast path, `LIVE_HOURS = 24`)
- `3d`, `1w`, `2w`, `1m`, `6m` → SQLite query (pre-indexed historical)
- Adding a new range: update `TIME_RANGE_HOURS` in `backend.py` AND `TIME_RANGES` array in `frontend/src/App.jsx`.

### SQLite upserts are fire-and-forget
Upserts run in a thread pool via `_upsert_in_background()` — never await them in the WS loop. Exceptions are logged but never propagated to the client.

### lifespan handler (not `on_event`)
Use FastAPI's `@asynccontextmanager` lifespan for startup/shutdown — `@app.on_event("startup")` is deprecated and was replaced during PR #2 Copilot review.

### `_normalize_ts` for timestamp consistency
All timestamps stored to SQLite go through `_normalize_ts` to ensure UTC `+00:00` format. Timezone-naive strings are treated as UTC. This prevents cutoff query mismatches.

### Logging uses `logging.getLogger`, not `print`
The project uses uvicorn's logging system — `logging.getLogger(__name__)` not a module-level `logger = ...` at file top.

### `npm ci --legacy-peer-deps` in Docker
`eslint-plugin-react@7.37.5` doesn't declare eslint@10 compatibility. Local installs work because `node_modules` already exists; Docker clean installs need `--legacy-peer-deps` in the Dockerfile.

### `frontend/.npmrc` with `legacy-peer-deps=true`
Same peer dep issue affects CI. Added `frontend/.npmrc` so `npm ci` works in GitHub Actions without extra flags.

## Frontend

### No TypeScript, no state management library
Plain JavaScript throughout. No Redux, Zustand, or Context API for state — pure React hooks only.

### No Tailwind, no CSS-in-JS
Plain CSS files per component (`ComponentName.css`). BEM-like naming. Styling is in `.css` files, not in JSX.

### Helper formatters live in `App.jsx`
`fmt`, `fmtCost`, `timeAgo`, `modelShort` are defined once in `App.jsx`. Don't duplicate them in child components — import or pass as props.

### `react/prop-types` rule disabled
This project doesn't use PropTypes. The ESLint rule is turned off — don't add PropTypes to new components.

### `intentionalCloseRef` pattern for WebSocket reconnect
When the WebSocket is deliberately closed (e.g., on time range change), set `intentionalCloseRef.current = true` before closing to suppress the auto-reconnect in the `onclose` handler.

### User preferences persisted via `localStorage`
Filter/sort/time-range state is persisted in `localStorage` under a `PREFS_DEFAULTS` shape. New preference keys go into `PREFS_DEFAULTS` even if the consuming feature isn't merged yet — they stay dormant until the feature lands.

## Infrastructure

### launchd plist owns port 8765
`~/Library/LaunchAgents/com.marie.claude-sessions-ui.plist` runs `start.sh` as a permanent service with `KeepAlive`. It always wins the port race over Docker. To test Docker, either stop the launchd service first or rebuild `frontend/dist/` locally so both paths serve the same code.

### FTS5 for full-text search
Per `docs/plans/01-full-text-search.md`: use SQLite FTS5 virtual table for full-text search over sessions. Parameterized queries only — never interpolate user input into FTS queries.

### Path traversal validation pattern (Memory Explorer)
Per `docs/plans/06-memory-explorer.md`: `validate_memory_path()` resolves the full path with `Path.resolve()`, checks it starts with `CLAUDE_BASE_DIR.resolve()`, and enforces an explicit allowlist. Symlinks are skipped in directory enumeration. Null bytes rejected before `Path()` construction.

### OLLAMA_URL in docker-compose uses shell default
`${OLLAMA_URL:-http://host.docker.internal:11434}` — users can override, but it defaults to the Docker host so Ollama on the Mac is reachable from inside the container.
