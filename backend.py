#!/usr/bin/env python3
"""Claude Sessions UI — FastAPI backend."""

import asyncio
import contextlib
import json
import logging
import os
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psutil
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Gauge,
    generate_latest,
)

logger = logging.getLogger(__name__)

# ─── Prometheus metrics ───────────────────────────────────────────────────────

sessions_total = Gauge("claude_sessions_total", "Total Claude sessions scanned")
sessions_active = Gauge("claude_sessions_active", "Currently active Claude sessions")
tokens_input = Gauge("claude_tokens_input_total", "Total input tokens across all sessions")
tokens_output = Gauge("claude_tokens_output_total", "Total output tokens across all sessions")
tokens_cache_create = Gauge("claude_tokens_cache_create_total", "Total cache-creation tokens")
tokens_cache_read = Gauge("claude_tokens_cache_read_total", "Total cache-read tokens")
cost_total = Gauge("claude_cost_usd_total", "Estimated total cost USD across all sessions")
cost_today = Gauge("claude_cost_usd_today", "Estimated cost USD for today")
turns_total = Gauge("claude_turns_total", "Total conversation turns across all sessions")
subagents_total = Gauge("claude_subagents_total", "Total subagents spawned across all sessions")

# ─── App setup ────────────────────────────────────────────────────────────────


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    asyncio.create_task(_startup_backfill())
    asyncio.create_task(backfill_daily_costs())
    yield
    # Shutdown: acquire the lock so we don't race with in-flight upsert threads,
    # then close the connection to release file locks/descriptors.
    global _db_conn
    with _db_lock:
        if _db_conn is not None:
            _db_conn.close()
            _db_conn = None


app = FastAPI(title="Claude Sessions UI", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

CLAUDE_DIR = Path.home() / ".claude" / "projects"
DB_PATH = Path.home() / ".claude" / "claude-sessions-ui.db"
LIVE_HOURS = 24  # Use JSONL for this window; SQLite for everything older

TIME_RANGE_HOURS: dict[str, int | None] = {
    "1h":  1,
    "1d":  24,
    "3d":  72,
    "1w":  168,
    "2w":  336,
    "1m":  720,
    "6m":  4320,
    "all": None,   # None = no cutoff
}

SUMMARIES_DIR = Path.home() / ".claude" / "session_summaries"
SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)

SKILLS_DIR = Path.home() / ".claude" / "skills"

SAVINGS_FILE = Path.home() / ".claude" / "pr_poller" / "ollama_savings.jsonl"
TRUNCATION_SAVINGS_FILE = Path.home() / ".claude" / "truncation_savings.jsonl"

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
SUMMARY_MODEL = "llama3.2:3b"

CONFIG_PATH = Path.home() / ".claude" / "claude-sessions-ui-config.json"
_config_cache: tuple[float, dict] | None = None


def _read_config_from_disk() -> dict:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"daily_budget_usd": None, "weekly_budget_usd": None}


def read_config() -> dict:
    global _config_cache
    now = time.monotonic()
    if _config_cache and now - _config_cache[0] < 5:
        return _config_cache[1]
    data = _read_config_from_disk()
    _config_cache = (now, data)
    return data


def write_config(data: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(data, indent=2))
    global _config_cache
    _config_cache = None  # invalidate cache


CLAUDE_BASE_DIR = Path.home() / ".claude"

MEMORY_ALLOWLIST = [
    "memory",
    "projects",
    "commands",
    "agents",
    "skills",
    "hooks",
    "todos",
]
MEMORY_ALLOWLIST_FILES = [
    "settings.json",
    "settings.local.json",
    "CLAUDE.md",
]

# Cost we'd pay for one summary via Claude Haiku (~500 input + ~15 output tokens)
SUMMARY_COST_ESTIMATE_USD = round(500 * 0.8 / 1_000_000 + 15 * 4.0 / 1_000_000, 6)  # ~$0.00046

MODEL_PRICING: dict[str, dict[str, float]] = {
    # Prices per million tokens
    "claude-opus-4-6":              {"input": 15.00, "output": 75.00, "cache_write":  18.75, "cache_read": 1.50},
    "claude-sonnet-4-6":            {"input":  3.00, "output": 15.00, "cache_write":   3.75, "cache_read": 0.30},
    "claude-sonnet-4-5":            {"input":  3.00, "output": 15.00, "cache_write":   3.75, "cache_read": 0.30},
    "claude-haiku-4-5":             {"input":  0.80, "output":  4.00, "cache_write":   1.00, "cache_read": 0.08},
    "claude-haiku-4-5-20251001":    {"input":  0.80, "output":  4.00, "cache_write":   1.00, "cache_read": 0.08},
    "claude-3-5-sonnet-20241022":   {"input":  3.00, "output": 15.00, "cache_write":   3.75, "cache_read": 0.30},
    "claude-3-5-haiku-20241022":    {"input":  0.80, "output":  4.00, "cache_write":   1.00, "cache_read": 0.08},
    "claude-3-opus-20240229":       {"input": 15.00, "output": 75.00, "cache_write":  18.75, "cache_read": 1.50},
    "default":                      {"input":  3.00, "output": 15.00, "cache_write":   3.75, "cache_read": 0.30},
}

# ─── Caches ───────────────────────────────────────────────────────────────────

# file path → (mtime, parsed session dict)
_session_cache: dict[str, tuple[float, dict]] = {}

# file path → (mtime, cwd string)  — quick first-pass scan
_cwd_cache: dict[str, tuple[float, str]] = {}

# file path → (mtime, analytics dict)
_analytics_cache: dict[str, tuple[float, dict]] = {}

# SQLite connection and lock
_db_conn: sqlite3.Connection | None = None
_db_lock = threading.Lock()


# ─── SQLite storage ──────────────────────────────────────────────────────────


@contextlib.contextmanager
def get_db():
    """Yield the shared SQLite connection under the write lock."""
    with _db_lock:
        yield _db_conn


def _normalize_ts(ts: str) -> str:
    """Normalize an ISO 8601 timestamp to consistent +00:00 UTC format for SQLite sorting.

    JSONL files use the 'Z' suffix; Python isoformat() uses '+00:00'. Storing a
    mix causes lexicographic range queries to mis-sort because 'Z' (0x5A) sorts
    after '+' (0x2B) in ASCII. This converts both forms to the +00:00 variant.
    """
    if not ts:
        return ts
    try:
        normalized = ts[:-1] + "+00:00" if ts.endswith("Z") else ts
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.isoformat()
    except (ValueError, AttributeError):
        return ts


def init_db() -> None:
    """Create the SQLite DB, table, and indexes. Must be called once at startup."""
    global _db_conn
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if _db_conn is not None:
        _db_conn.close()
    _db_conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    _db_conn.execute("PRAGMA journal_mode=WAL")
    _db_conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id            TEXT PRIMARY KEY,
            project_path          TEXT NOT NULL,
            project_name          TEXT NOT NULL,
            git_branch            TEXT,
            title                 TEXT NOT NULL,
            model                 TEXT NOT NULL,
            turns                 INTEGER NOT NULL DEFAULT 0,
            subagent_count        INTEGER NOT NULL DEFAULT 0,
            subagents_json        TEXT NOT NULL DEFAULT '[]',
            started_at            TEXT NOT NULL,
            last_active           TEXT NOT NULL,
            input_tokens          INTEGER NOT NULL DEFAULT 0,
            output_tokens         INTEGER NOT NULL DEFAULT 0,
            cache_create_tokens   INTEGER NOT NULL DEFAULT 0,
            cache_read_tokens     INTEGER NOT NULL DEFAULT 0,
            total_tokens          INTEGER NOT NULL DEFAULT 0,
            estimated_cost_usd    REAL NOT NULL DEFAULT 0.0,
            compact_potential_usd REAL NOT NULL DEFAULT 0.0,
            last_synced_at        TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sessions_last_active ON sessions(last_active);
        CREATE INDEX IF NOT EXISTS idx_sessions_started_at  ON sessions(started_at);
    """)
    _db_conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_costs (
            date            TEXT PRIMARY KEY,
            total_cost_usd  REAL NOT NULL DEFAULT 0.0,
            model_breakdown TEXT NOT NULL DEFAULT '{}',
            session_count   INT  NOT NULL DEFAULT 0,
            last_synced_at  TEXT
        )
    """)
    # Migrate: add last_activity column if it doesn't exist (SQLite has no ADD COLUMN IF NOT EXISTS)
    with contextlib.suppress(sqlite3.OperationalError):
        _db_conn.execute("ALTER TABLE sessions ADD COLUMN last_activity TEXT")
    _db_conn.commit()


def upsert_sessions_to_db(sessions: list[dict]) -> None:
    """Upsert a list of session dicts into the SQLite DB."""
    if not sessions or _db_conn is None:
        return
    now_iso = datetime.now(UTC).isoformat()
    rows = [
        (
            s["session_id"],
            s["project_path"],
            s["project_name"],
            s.get("git_branch"),
            s["title"],
            s["model"],
            s["turns"],
            s["subagent_count"],
            json.dumps(s.get("subagents", [])),
            _normalize_ts(s["started_at"]),
            _normalize_ts(s["last_active"]),
            s["stats"]["input_tokens"],
            s["stats"]["output_tokens"],
            s["stats"]["cache_create_tokens"],
            s["stats"]["cache_read_tokens"],
            s["stats"]["total_tokens"],
            s["stats"]["estimated_cost_usd"],
            s.get("compact_potential_usd", 0.0),
            now_iso,
            s.get("last_activity"),
        )
        for s in sessions
    ]
    with _db_lock:
        _db_conn.executemany(
            """
            INSERT INTO sessions (
                session_id, project_path, project_name, git_branch, title, model,
                turns, subagent_count, subagents_json, started_at, last_active,
                input_tokens, output_tokens, cache_create_tokens, cache_read_tokens,
                total_tokens, estimated_cost_usd, compact_potential_usd, last_synced_at,
                last_activity
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(session_id) DO UPDATE SET
                project_path=excluded.project_path,
                project_name=excluded.project_name,
                git_branch=excluded.git_branch,
                title=excluded.title,
                model=excluded.model,
                turns=excluded.turns,
                subagent_count=excluded.subagent_count,
                subagents_json=excluded.subagents_json,
                last_active=excluded.last_active,
                input_tokens=excluded.input_tokens,
                output_tokens=excluded.output_tokens,
                cache_create_tokens=excluded.cache_create_tokens,
                cache_read_tokens=excluded.cache_read_tokens,
                total_tokens=excluded.total_tokens,
                estimated_cost_usd=excluded.estimated_cost_usd,
                compact_potential_usd=excluded.compact_potential_usd,
                last_synced_at=excluded.last_synced_at,
                last_activity=excluded.last_activity
            """,
            rows,
        )
        # Recompute daily_costs for each affected date from the sessions table.
        # Using INSERT OR REPLACE with aggregated totals ensures idempotency —
        # repeated upserts of the same sessions never inflate the daily totals.
        affected_dates: set[str] = set()
        for s in sessions:
            started_at = s.get("started_at")
            if started_at:
                with contextlib.suppress(Exception):
                    affected_dates.add(_normalize_ts(started_at)[:10])  # "YYYY-MM-DD"
        now_iso = datetime.now(UTC).isoformat()
        for date_str in affected_dates:
            try:
                model_rows = _db_conn.execute(
                    "SELECT model, SUM(estimated_cost_usd), COUNT(*) "
                    "FROM sessions WHERE DATE(started_at) = ? GROUP BY model",
                    (date_str,),
                ).fetchall()
                if not model_rows:
                    continue
                breakdown: dict[str, float] = {}
                total_cost = 0.0
                total_count = 0
                for model_name, cost_sum, count in model_rows:
                    key = model_name or "unknown"
                    breakdown[key] = round(cost_sum or 0.0, 6)
                    total_cost += cost_sum or 0.0
                    total_count += count or 0
                _db_conn.execute(
                    "INSERT OR REPLACE INTO daily_costs VALUES (?, ?, ?, ?, ?)",
                    (date_str, total_cost, json.dumps(breakdown), total_count, now_iso),
                )
            except Exception:
                pass
        _db_conn.commit()


def get_sessions_from_db(
    hours: int | None = None,
    start: str | None = None,
    end: str | None = None,
) -> list[dict]:
    """Return sessions from SQLite for time ranges beyond LIVE_HOURS."""
    if _db_conn is None:
        return []
    conditions = []
    params = []

    if start:
        conditions.append("last_active >= ?")
        params.append(start)
    if end:
        conditions.append("last_active <= ?")
        params.append(end)
    if hours is not None and not start and not end:
        cutoff = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
        conditions.append("last_active >= ?")
        params.append(cutoff)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    processes = get_running_claude_processes()
    session_pid: dict[str, int] = {
        info["session_id"]: pid
        for pid, info in processes.items()
        if info["session_id"]
    }
    with _db_lock:
        cur = _db_conn.execute(
            f"SELECT * FROM sessions {where} ORDER BY last_active DESC",
            params,
        )
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    sessions = []
    for row in rows:
        s: dict = {
            "session_id": row["session_id"],
            "project_path": row["project_path"],
            "project_name": row["project_name"],
            "git_branch": row["git_branch"],
            "title": row["title"],
            "model": row["model"],
            "turns": row["turns"],
            "subagent_count": row["subagent_count"],
            "subagents": json.loads(row["subagents_json"]),
            "started_at": row["started_at"],
            "last_active": row["last_active"],
            "last_activity": row.get("last_activity"),
            "stats": {
                "input_tokens": row["input_tokens"],
                "output_tokens": row["output_tokens"],
                "cache_create_tokens": row["cache_create_tokens"],
                "cache_read_tokens": row["cache_read_tokens"],
                "total_tokens": row["total_tokens"],
                "estimated_cost_usd": row["estimated_cost_usd"],
            },
            "compact_potential_usd": row["compact_potential_usd"],
            "is_active": False,
            "pid": None,
            "ai_summary": get_cached_summary(row["session_id"]),
        }
        if row["session_id"] in session_pid:
            s["is_active"] = True
            s["pid"] = session_pid[row["session_id"]]
        sessions.append(s)

    sessions.sort(key=lambda s: not s["is_active"])
    return sessions


def get_sessions_for_range(
    time_range: str,
    start: str | None = None,
    end: str | None = None,
) -> list[dict]:
    """Dispatch to JSONL (short ranges) or SQLite (historical ranges)."""
    hours = TIME_RANGE_HOURS.get(time_range, 24)

    # Custom range always routes to SQLite
    if start or end:
        return get_sessions_from_db(start=start, end=end)

    # "all" routes to SQLite with no cutoff
    if hours is None:
        return get_sessions_from_db()

    # Existing routing logic unchanged
    if hours <= LIVE_HOURS:
        return get_all_sessions(hours=hours)
    return get_sessions_from_db(hours=hours)


def get_all_sessions_unbounded() -> list[dict]:
    """Parse all JSONL sessions regardless of age — used for startup DB backfill."""
    return get_all_sessions(hours=None)


def get_session_by_id(session_id: str) -> dict | None:
    """Return a single session dict by ID, checking SQLite first then JSONL fallback."""
    # Try SQLite first (covers historical sessions not in the live 24h window)
    if _db_conn is not None:
        with _db_lock:
            cur = _db_conn.execute(
                "SELECT title FROM sessions WHERE session_id = ?", (session_id,)
            )
            row = cur.fetchone()
        if row is not None:
            return {"session_id": session_id, "title": row[0]}
    # Fall back to JSONL for sessions within the live window
    sessions = get_all_sessions()
    return next((s for s in sessions if s["session_id"] == session_id), None)


async def _startup_backfill() -> None:
    """Asynchronously backfill all historical JSONL sessions into SQLite."""
    try:
        loop = asyncio.get_running_loop()
        sessions = await loop.run_in_executor(None, get_all_sessions_unbounded)
        await loop.run_in_executor(None, upsert_sessions_to_db, sessions)
        logger.info("Startup backfill complete: %d sessions stored", len(sessions))
    except Exception:
        logger.exception("Startup backfill failed")


async def _upsert_in_background(sessions: list[dict]) -> None:
    """Run upsert_sessions_to_db in a thread pool, logging any error instead of dropping it."""
    try:
        await asyncio.get_running_loop().run_in_executor(None, upsert_sessions_to_db, sessions)
    except Exception:
        logger.exception("Background SQLite upsert failed")


async def backfill_daily_costs() -> None:
    def _run():
        with get_db() as conn:
            rows = conn.execute(
                "SELECT DATE(started_at) AS date, model, SUM(estimated_cost_usd), COUNT(*) "
                "FROM sessions WHERE started_at IS NOT NULL GROUP BY DATE(started_at), model"
            ).fetchall()
            by_date: dict[str, dict] = {}
            for date_str, model, cost, count in rows:
                if not date_str:
                    continue
                if date_str not in by_date:
                    by_date[date_str] = {"total": 0.0, "models": {}, "count": 0}
                by_date[date_str]["total"] += cost or 0.0
                by_date[date_str]["models"][model or "unknown"] = (
                    by_date[date_str]["models"].get(model or "unknown", 0.0) + (cost or 0.0)
                )
                by_date[date_str]["count"] += count or 0
            for date_str, data in by_date.items():
                conn.execute(
                    "INSERT OR REPLACE INTO daily_costs VALUES (?, ?, ?, ?, ?)",
                    (date_str, data["total"], json.dumps(data["models"]),
                     data["count"], datetime.now(UTC).isoformat()),
                )
            conn.commit()

    await asyncio.get_running_loop().run_in_executor(None, _run)


# ─── Process discovery ────────────────────────────────────────────────────────

def get_running_claude_processes() -> dict[int, dict]:
    """Return {pid: {cwd, session_id, create_time}} for all claude processes."""
    result: dict[int, dict] = {}
    for p in psutil.process_iter(["pid", "name", "cmdline", "cwd", "create_time"]):
        try:
            name = p.info["name"] or ""
            cmdline = p.info["cmdline"] or []
            is_claude = name == "claude" or any(
                c.endswith("/claude") or c.endswith("/claude-code") or c == "claude"
                for c in cmdline[:2] if c
            )
            if not is_claude:
                continue
            session_id = None
            for i, arg in enumerate(cmdline):
                if arg == "--resume" and i + 1 < len(cmdline):
                    session_id = cmdline[i + 1]
                    break
            result[p.info["pid"]] = {
                "pid": p.info["pid"],
                "cwd": p.info["cwd"],
                "session_id": session_id,
                "create_time": p.info["create_time"],
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return result


# ─── Session parsing ──────────────────────────────────────────────────────────

def get_session_cwd(jsonl_path: Path) -> str | None:
    """Quick scan for cwd in the first 25 lines."""
    key = str(jsonl_path)
    try:
        mtime = jsonl_path.stat().st_mtime
    except OSError:
        return None
    if key in _cwd_cache and _cwd_cache[key][0] == mtime:
        return _cwd_cache[key][1]
    try:
        with open(jsonl_path) as f:
            for i, line in enumerate(f):
                if i > 25:
                    break
                try:
                    d = json.loads(line)
                    if d.get("cwd"):
                        _cwd_cache[key] = (mtime, d["cwd"])
                        return d["cwd"]
                except (json.JSONDecodeError, KeyError):
                    pass
    except OSError:
        pass
    return None


def parse_session_file(jsonl_path: Path, project_path: str) -> dict | None:
    """Parse a JSONL session file into a session dict (with mtime-based cache)."""
    key = str(jsonl_path)
    try:
        mtime = jsonl_path.stat().st_mtime
    except OSError:
        return None

    if key in _session_cache and _session_cache[key][0] == mtime:
        return _session_cache[key][1]

    usage = {"input": 0, "output": 0, "cache_create": 0, "cache_read": 0}
    model: str | None = None
    git_branch: str | None = None
    first_user_text: str | None = None
    last_tool_name: str | None = None
    last_assistant_snippet: str | None = None
    turns = 0
    first_timestamp: str | None = None
    last_timestamp: str | None = None

    try:
        with open(jsonl_path) as f:
            for raw_line in f:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    d = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue

                t = d.get("type")
                ts = d.get("timestamp")
                if ts:
                    if first_timestamp is None:
                        first_timestamp = ts
                    last_timestamp = ts

                if not git_branch and d.get("gitBranch"):
                    git_branch = d["gitBranch"]

                if t == "user":
                    msg = d.get("message", {})
                    content = msg.get("content", "")
                    text = ""
                    if isinstance(content, str):
                        text = content
                    elif isinstance(content, list):
                        for c in content:
                            if isinstance(c, dict) and c.get("type") == "text":
                                text = c.get("text", "")
                                break
                    if text and not isinstance(msg.get("content"), list):
                        # plain text user message (not tool results)
                        if first_user_text is None:
                            first_user_text = text
                        turns += 1
                    elif text:
                        # could be tool result list — check for actual human input
                        has_tool_result = any(
                            isinstance(c, dict) and c.get("type") == "tool_result"
                            for c in (content if isinstance(content, list) else [])
                        )
                        if not has_tool_result:
                            if first_user_text is None:
                                first_user_text = text
                            turns += 1

                elif t == "assistant":
                    msg = d.get("message", {})
                    if not model:
                        model = msg.get("model")
                    u = msg.get("usage", {})
                    usage["input"] += u.get("input_tokens", 0)
                    usage["output"] += u.get("output_tokens", 0)
                    usage["cache_create"] += u.get("cache_creation_input_tokens", 0)
                    usage["cache_read"] += u.get("cache_read_input_tokens", 0)
                    content = msg.get("content", [])
                    if isinstance(content, list):
                        for c in content:
                            if isinstance(c, dict):
                                if c.get("type") == "text" and c.get("text"):
                                    last_assistant_snippet = c["text"][:120]
                                elif c.get("type") == "tool_use":
                                    last_tool_name = c.get("name")

    except OSError:
        return None

    if not first_timestamp:
        stat = jsonl_path.stat()
        first_timestamp = datetime.fromtimestamp(
            stat.st_ctime, tz=UTC
        ).isoformat()

    pricing = MODEL_PRICING.get(model or "", MODEL_PRICING["default"])
    cost = (
        usage["input"]        * pricing["input"]        / 1_000_000
        + usage["output"]       * pricing["output"]       / 1_000_000
        + usage["cache_create"] * pricing["cache_write"]  / 1_000_000
        + usage["cache_read"]   * pricing["cache_read"]   / 1_000_000
    )

    session_id = jsonl_path.stem
    subagents_dir = jsonl_path.parent / session_id / "subagents"
    subagents = []
    if subagents_dir.exists():
        for meta_file in subagents_dir.glob("*.meta.json"):
            try:
                with open(meta_file) as f:
                    meta = json.load(f)
                agent_id = meta_file.name.replace(".meta.json", "")
                subagents.append(
                    {"id": agent_id, "agent_type": meta.get("agentType", "general-purpose")}
                )
            except (OSError, json.JSONDecodeError):
                pass

    # Estimate potential savings from running /compact:
    # If turns > 10, each new turn repeats ~cache_read_tokens worth of context.
    # Compaction reduces that by ~50%.  Show savings over the next 10 hypothetical turns.
    compact_potential_usd = 0.0
    if turns > 10 and usage["cache_read"] > 0:
        per_turn_cache_cost = usage["cache_read"] / turns * pricing["cache_read"] / 1_000_000
        compact_potential_usd = round(per_turn_cache_cost * 10 * 0.5, 6)

    data: dict = {
        "session_id": session_id,
        "project_path": project_path,
        "project_name": Path(project_path).name,
        "git_branch": git_branch,
        "title": (first_user_text or "Untitled session")[:150],
        "last_activity": last_tool_name or (last_assistant_snippet or None),
        "model": model or "unknown",
        "turns": turns,
        "subagents": subagents,
        "subagent_count": len(subagents),
        "started_at": first_timestamp,
        "last_active": last_timestamp or first_timestamp,
        "stats": {
            "input_tokens": usage["input"],
            "output_tokens": usage["output"],
            "cache_create_tokens": usage["cache_create"],
            "cache_read_tokens": usage["cache_read"],
            "total_tokens": sum(usage.values()),
            "estimated_cost_usd": round(cost, 6),
        },
        "compact_potential_usd": compact_potential_usd,
        "is_active": False,
        "pid": None,
    }

    _session_cache[key] = (mtime, data)
    return data


# ─── Session aggregation ─────────────────────────────────────────────────────

def _norm_ts(ts: str | None) -> str:
    """Normalize ISO timestamp to +00:00 format for lexicographic comparison.

    Handles the mix of Z-suffix and +00:00-suffix timestamps that appear in
    JSONL session files, ensuring min/max comparisons work correctly.
    """
    if not ts:
        return ""
    return ts.replace("Z", "+00:00")


def compute_project_stats(sessions: list[dict]) -> list[dict]:
    # Key by project_path (falls back to project_name) so distinct projects
    # that share a display name are not incorrectly merged.
    projects: dict[str, dict] = {}
    for s in sessions:
        name = s.get("project_name") or "unknown"
        path = s.get("project_path", "")
        key = path or name
        if key not in projects:
            projects[key] = {
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
        p = projects[key]
        p["session_count"] += 1
        stats = s.get("stats", {})
        p["total_cost_usd"] += stats.get("estimated_cost_usd", 0.0)
        p["total_tokens"] += stats.get("total_tokens", 0)
        p["total_input_tokens"] += stats.get("input_tokens", 0)
        p["total_output_tokens"] += stats.get("output_tokens", 0)
        p["models"].add(s.get("model", "unknown"))
        started = s.get("started_at")
        active = s.get("last_active")
        # Normalize timestamps before comparing to handle Z vs +00:00 suffix mix
        if started and p["first_session"] and _norm_ts(started) < _norm_ts(p["first_session"]):
            p["first_session"] = started
        if active and p["last_session"] and _norm_ts(active) > _norm_ts(p["last_session"]):
            p["last_session"] = active

    for p in projects.values():
        p["models"] = sorted(p["models"])

    return sorted(projects.values(), key=lambda p: p["total_cost_usd"], reverse=True)


def get_all_sessions(hours: int | None = 24) -> list[dict]:
    if not CLAUDE_DIR.exists():
        return []

    processes = get_running_claude_processes()
    cwd_pids: dict[str, list[int]] = {}
    session_pid: dict[str, int] = {}

    for pid, info in processes.items():
        if info["cwd"]:
            cwd_pids.setdefault(info["cwd"], []).append(pid)
        if info["session_id"]:
            session_pid[info["session_id"]] = pid

    now = time.time()
    cutoff = (now - hours * 3600) if hours is not None else 0
    sessions: list[dict] = []

    # For CWD-based matching (no --resume), only the NEWEST session in each
    # project dir should be considered active.  Pre-compute: cwd → newest mtime.
    cwd_newest_mtime: dict[str, float] = {}

    for project_dir in CLAUDE_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        for jsonl_file in project_dir.glob("*.jsonl"):
            try:
                mtime = jsonl_file.stat().st_mtime
            except OSError:
                continue
            if mtime < cutoff:
                continue
            cwd = get_session_cwd(jsonl_file)
            if cwd and cwd in cwd_pids and mtime > cwd_newest_mtime.get(cwd, 0):
                cwd_newest_mtime[cwd] = mtime

    for project_dir in CLAUDE_DIR.iterdir():
        if not project_dir.is_dir():
            continue

        for jsonl_file in project_dir.glob("*.jsonl"):
            try:
                mtime = jsonl_file.stat().st_mtime
            except OSError:
                continue
            if mtime < cutoff:
                continue

            cwd = get_session_cwd(jsonl_file)
            project_path = cwd or ("/" + project_dir.name.lstrip("-"))

            session = parse_session_file(jsonl_file, project_path)
            if session is None:
                continue

            # Shallow copy so we can annotate is_active/pid/summary without dirtying cache
            session = dict(session)
            session["ai_summary"] = get_cached_summary(session["session_id"])

            sid = session["session_id"]
            if sid in session_pid:
                # Direct --resume match: always authoritative
                session["is_active"] = True
                session["pid"] = session_pid[sid]
            elif (
                cwd
                and cwd in cwd_pids
                and mtime == cwd_newest_mtime.get(cwd, -1)
            ):
                # CWD match: only the newest session in this dir is active
                session["is_active"] = True
                session["pid"] = cwd_pids[cwd][0]

            sessions.append(session)

    sessions.sort(key=lambda s: (not s["is_active"], s.get("last_active") or ""), reverse=False)
    sessions.sort(key=lambda s: not s["is_active"])
    return sessions


def compute_global_stats(sessions: list[dict], time_range_hours: int = 24) -> dict:
    active_count = sum(1 for s in sessions if s["is_active"])
    total_cost = sum(s["stats"]["estimated_cost_usd"] for s in sessions)
    total_tokens = sum(s["stats"]["total_tokens"] for s in sessions)
    total_input = sum(s["stats"]["input_tokens"] for s in sessions)
    total_output = sum(s["stats"]["output_tokens"] for s in sessions)
    total_cache_create = sum(s["stats"]["cache_create_tokens"] for s in sessions)
    total_cache_read = sum(s["stats"]["cache_read_tokens"] for s in sessions)
    total_turns = sum(s["turns"] for s in sessions)
    total_subagents = sum(s["subagent_count"] for s in sessions)

    period_cutoff = datetime.now(UTC) - timedelta(hours=time_range_hours)
    def _in_period(ts: str | None) -> bool:
        if not ts:
            return False
        try:
            return datetime.fromisoformat(_normalize_ts(ts)) >= period_cutoff
        except ValueError:
            return False
    cost_today_val = sum(
        s["stats"]["estimated_cost_usd"]
        for s in sessions
        if _in_period(s.get("last_active"))
    )

    return {
        "total_sessions": len(sessions),
        "active_sessions": active_count,
        "total_cost_usd": round(total_cost, 4),
        "cost_today_usd": round(cost_today_val, 4),
        "total_tokens": total_tokens,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_cache_create_tokens": total_cache_create,
        "total_cache_read_tokens": total_cache_read,
        "total_turns": total_turns,
        "total_subagents": total_subagents,
    }


def _update_prometheus(stats: dict) -> None:
    sessions_total.set(stats["total_sessions"])
    sessions_active.set(stats["active_sessions"])
    tokens_input.set(stats["total_input_tokens"])
    tokens_output.set(stats["total_output_tokens"])
    tokens_cache_create.set(stats["total_cache_create_tokens"])
    tokens_cache_read.set(stats["total_cache_read_tokens"])
    cost_total.set(stats["total_cost_usd"])
    cost_today.set(stats["cost_today_usd"])
    turns_total.set(stats["total_turns"])
    subagents_total.set(stats["total_subagents"])


# ─── Ollama helpers ──────────────────────────────────────────────────────────

def ollama_is_available() -> bool:
    try:
        req = urllib.request.Request(f"{OLLAMA_URL}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3):
            return True
    except Exception:
        return False


def ollama_model_pulled(model: str) -> bool:
    try:
        req = urllib.request.Request(f"{OLLAMA_URL}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
        names = [m["name"] for m in data.get("models", [])]
        base = model.split(":")[0]
        return any(base in n for n in names)
    except Exception:
        return False


def ollama_summarize(text: str, model: str = SUMMARY_MODEL) -> str | None:
    """Call local Ollama to produce a short task title from a raw user message."""
    prompt = (
        "Summarize this task request in 6-10 words. "
        "Start with a verb. No punctuation at the end. Be specific.\n\n"
        + text[:600]
    )
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode()
    try:
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read()).get("response", "").strip()
            # Strip surrounding quotes if model added them
            return result.strip('"').strip("'")
    except Exception:
        return None


def get_cached_summary(session_id: str) -> str | None:
    p = SUMMARIES_DIR / f"{session_id}.txt"
    try:
        return p.read_text().strip() or None
    except OSError:
        return None


def cache_summary(session_id: str, summary: str) -> None:
    (SUMMARIES_DIR / f"{session_id}.txt").write_text(summary)


def compute_truncation_savings() -> dict:
    """Read truncation hook log and aggregate savings per tool."""
    by_tool: dict[str, dict] = {}
    if not TRUNCATION_SAVINGS_FILE.exists():
        return {"tools": {}, "total_tokens_saved": 0, "total_cost_saved_usd": 0.0}
    try:
        for line in TRUNCATION_SAVINGS_FILE.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            tool = e.get("tool", "Unknown")
            if tool not in by_tool:
                by_tool[tool] = {"count": 0, "tokens_saved": 0, "cost_saved_usd": 0.0}
            by_tool[tool]["count"] += 1
            by_tool[tool]["tokens_saved"] += e.get("tokens_saved", 0)
            by_tool[tool]["cost_saved_usd"] = round(
                by_tool[tool]["cost_saved_usd"] + e.get("cost_saved_usd", 0.0), 6
            )
    except OSError:
        pass

    total_tokens = sum(v["tokens_saved"] for v in by_tool.values())
    total_cost = round(sum(v["cost_saved_usd"] for v in by_tool.values()), 4)
    return {
        "tools": by_tool,
        "total_tokens_saved": total_tokens,
        "total_cost_saved_usd": total_cost,
    }


def compute_ollama_savings() -> dict:
    """Read pr_poller savings log + summary cache to compute total saved cost."""
    pr_skips: list[dict] = []
    if SAVINGS_FILE.exists():
        try:
            for line in SAVINGS_FILE.read_text().splitlines():
                line = line.strip()
                if line:
                    with contextlib.suppress(json.JSONDecodeError):
                        pr_skips.append(json.loads(line))
        except OSError:
            pass

    summary_count = len(list(SUMMARIES_DIR.glob("*.txt")))

    pr_skip_count = len(pr_skips)
    pr_saved_usd = sum(float(e.get("saved_usd", 0)) for e in pr_skips)
    summary_saved_usd = summary_count * SUMMARY_COST_ESTIMATE_USD
    total_saved_usd = pr_saved_usd + summary_saved_usd

    return {
        "pr_skips": pr_skip_count,
        "pr_saved_usd": round(pr_saved_usd, 4),
        "summaries_generated": summary_count,
        "summary_saved_usd": round(summary_saved_usd, 6),
        "total_saved_usd": round(total_saved_usd, 4),
        "recent_skips": [
            {"ts": e.get("ts"), "title": e.get("title", ""), "url": e.get("url", "")}
            for e in pr_skips[-5:]  # last 5 for the UI
        ],
    }


# ─── Session detail helpers ──────────────────────────────────────────────────


def find_session_file(session_id: str) -> Path | None:
    """Scan ~/.claude/projects/ for {session_id}.jsonl. Returns None if not found."""
    for path in CLAUDE_DIR.glob(f"*/{session_id}.jsonl"):
        return path
    return None


def parse_session_detail(path: Path, offset: int = 0, limit: int = 200) -> dict:
    """Read a JSONL file and return structured, paginated message objects."""
    session_id = path.stem
    raw_lines: list[dict] = []

    try:
        with open(path) as f:
            for raw_line in f:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    raw_lines.append(json.loads(raw_line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return {"session_id": session_id, "total_messages": 0, "offset": offset, "limit": limit, "messages": []}

    # First pass: map tool_use_id → tool_name for pairing tool_result blocks
    tool_name_map: dict[str, str] = {}
    for d in raw_lines:
        if d.get("type") == "assistant":
            for block in d.get("message", {}).get("content", []):
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_name_map[block.get("id", "")] = block.get("name", "")

    # Second pass: normalize each line into flat message objects
    all_messages: list[dict] = []
    for idx, d in enumerate(raw_lines):
        t = d.get("type", "")
        ts = d.get("timestamp")

        if t == "user":
            content = d.get("message", {}).get("content", "")
            if isinstance(content, str):
                all_messages.append({
                    "id": idx, "type": "user", "role": "user", "content": content,
                    "tool_name": None, "tool_use_id": None, "timestamp": ts, "thinking": None,
                })
            elif isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    btype = block.get("type", "")
                    if btype == "tool_result":
                        tool_use_id = block.get("tool_use_id", "")
                        result_content = block.get("content", "")
                        if isinstance(result_content, list):
                            result_content = " ".join(
                                c.get("text", "")
                                for c in result_content
                                if isinstance(c, dict) and c.get("type") == "text"
                            )
                        if isinstance(result_content, str) and len(result_content) > 500:
                            result_content = result_content[:500] + "…[truncated]"
                        all_messages.append({
                            "id": idx, "type": "tool_result", "role": "tool",
                            "content": result_content,
                            "tool_name": tool_name_map.get(tool_use_id),
                            "tool_use_id": tool_use_id, "timestamp": ts, "thinking": None,
                        })
                    elif btype == "text":
                        text = block.get("text", "")
                        if text:
                            all_messages.append({
                                "id": idx, "type": "user", "role": "user", "content": text,
                                "tool_name": None, "tool_use_id": None, "timestamp": ts, "thinking": None,
                            })

        elif t == "assistant":
            thinking_text = None
            for block in d.get("message", {}).get("content", []):
                if not isinstance(block, dict):
                    continue
                btype = block.get("type", "")
                if btype == "thinking":
                    thinking_text = block.get("thinking", "")
                elif btype == "text":
                    all_messages.append({
                        "id": idx, "type": "assistant", "role": "assistant",
                        "content": block.get("text", ""),
                        "tool_name": None, "tool_use_id": None, "timestamp": ts,
                        "thinking": thinking_text,
                    })
                    thinking_text = None
                elif btype == "tool_use":
                    input_data = block.get("input", {})
                    input_str = json.dumps(input_data, indent=2) if isinstance(input_data, dict) else str(input_data)
                    if len(input_str) > 500:
                        input_str = input_str[:500] + "\n…[truncated]"
                    all_messages.append({
                        "id": idx, "type": "tool_use", "role": "assistant",
                        "content": input_str,
                        "tool_name": block.get("name"),
                        "tool_use_id": block.get("id"), "timestamp": ts, "thinking": None,
                    })

        elif t == "summary":
            summary_text = d.get("summary", "")
            if summary_text:
                all_messages.append({
                    "id": idx, "type": "summary", "role": "system", "content": summary_text,
                    "tool_name": None, "tool_use_id": None, "timestamp": ts, "thinking": None,
                })

    total = len(all_messages)
    return {
        "session_id": session_id,
        "total_messages": total,
        "offset": offset,
        "limit": limit,
        "messages": all_messages[offset:offset + limit],
    }


async def parse_session_analytics(session_id: str) -> dict | None:
    """Parse a JSONL session file into per-turn analytics with mtime-based caching."""
    matches = list(CLAUDE_DIR.glob(f"*/{session_id}.jsonl"))
    if not matches:
        return None
    jf = matches[0]

    mtime = jf.stat().st_mtime
    cache_key = str(jf)
    if cache_key in _analytics_cache and _analytics_cache[cache_key][0] == mtime:
        return _analytics_cache[cache_key][1]

    def _parse():
        from collections import Counter
        from datetime import datetime as _dt

        turns: list[dict] = []
        tool_counts: Counter = Counter()
        current_turn: dict = {}
        turn_number = 0

        def new_turn(ts: str) -> dict:
            return {
                "input": 0, "output": 0, "cache_create": 0, "cache_read": 0,
                "thinking": 0, "cost": 0.0, "start_ts": ts, "end_ts": ts,
                "tools": [],
            }

        def finalize_turn(t: dict, n: int, model: str) -> dict:
            pricing = MODEL_PRICING.get(model, MODEL_PRICING["default"])
            cost = (
                t["input"]          * pricing["input"]       / 1_000_000
                + t["output"]       * pricing["output"]      / 1_000_000
                + t["cache_create"] * pricing["cache_write"] / 1_000_000
                + t["cache_read"]   * pricing["cache_read"]  / 1_000_000
            )
            dur = None
            try:
                if t["start_ts"] and t["end_ts"]:
                    a = _dt.fromisoformat(t["start_ts"].replace("Z", "+00:00"))
                    b = _dt.fromisoformat(t["end_ts"].replace("Z", "+00:00"))
                    dur = (b - a).total_seconds()
            except Exception:
                pass
            return {
                "turn": n,
                "input_tokens": t["input"],
                "output_tokens": t["output"],
                "cache_create_tokens": t["cache_create"],
                "cache_read_tokens": t["cache_read"],
                "thinking_words": t["thinking"],
                "cost_usd": cost,
                "duration_s": dur,
                "ts": t["start_ts"],
            }

        model_used = "claude-sonnet-4-6"
        try:
            with open(jf, encoding="utf-8", errors="replace") as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    msg = entry.get("message", {}) or {}
                    role = msg.get("role") or entry.get("type", "")
                    ts = entry.get("timestamp", "")

                    if role == "user":
                        content = msg.get("content", "")
                        has_text = (
                            (isinstance(content, str) and content.strip()) or
                            (isinstance(content, list) and any(
                                isinstance(b, dict) and b.get("type") == "text" for b in content
                            ))
                        )
                        if has_text:
                            if current_turn and turn_number > 0:
                                turns.append(finalize_turn(current_turn, turn_number, model_used))
                            turn_number += 1
                            current_turn = new_turn(ts)

                    elif role == "assistant":
                        if not current_turn:
                            turn_number += 1
                            current_turn = new_turn(ts)
                        usage = msg.get("usage", {}) or {}
                        current_turn["input"]        += usage.get("input_tokens", 0) or 0
                        current_turn["output"]       += usage.get("output_tokens", 0) or 0
                        current_turn["cache_create"] += usage.get("cache_creation_input_tokens", 0) or 0
                        current_turn["cache_read"]   += usage.get("cache_read_input_tokens", 0) or 0
                        current_turn["end_ts"] = ts
                        m = msg.get("model", "")
                        if m:
                            model_used = m
                        for block in (msg.get("content") or []):
                            if isinstance(block, dict) and block.get("type") == "thinking":
                                think_text = block.get("thinking", "")
                                current_turn["thinking"] += len(think_text.split()) if think_text else 0

                    elif entry.get("type") in ("tool", "tool_result") or role in ("tool",):
                        tool_name = (
                            entry.get("toolName") or entry.get("tool_name") or
                            entry.get("name") or "Unknown"
                        )
                        tool_counts[tool_name] += 1
                        if current_turn:
                            current_turn["tools"].append(tool_name)

        except OSError:
            return None

        if current_turn and turn_number > 0:
            turns.append(finalize_turn(current_turn, turn_number, model_used))

        if not turns:
            return None

        # Cumulative cost
        cumulative = []
        running = 0.0
        for t in turns:
            running += t["cost_usd"]
            cumulative.append({"turn": t["turn"], "cost_usd": running})

        # Tool usage top 10
        tool_usage = [{"tool": t, "count": c} for t, c in tool_counts.most_common(10)]

        # Summary stats
        durations = [t["duration_s"] for t in turns if t["duration_s"] is not None]
        avg_dur = sum(durations) / len(durations) if durations else None
        total_output = sum(t["output_tokens"] for t in turns)
        # thinking_words is a word count (len(text.split()), not an API token count)
        total_thinking_words = sum(t["thinking_words"] for t in turns)
        thinking_word_ratio = total_thinking_words / total_output if total_output > 0 else 0.0
        peak = max(turns, key=lambda t: t["cost_usd"])

        return {
            "session_id": session_id,
            "turns": turns[:200],
            "truncated": len(turns) > 200,
            "cumulative_cost": cumulative[:200],
            "tool_usage": tool_usage,
            "summary": {
                "total_turns": len(turns),
                "avg_turn_duration_s": avg_dur,
                "thinking_word_ratio": thinking_word_ratio,
                "peak_turn": peak["turn"],
                "peak_turn_cost_usd": peak["cost_usd"],
            },
        }

    result = await asyncio.get_event_loop().run_in_executor(None, _parse)
    if result:
        _analytics_cache[cache_key] = (mtime, result)
    return result


# ─── Skill export helpers ─────────────────────────────────────────────────────

SKILL_PROMPT_TEMPLATE = """
You are creating a Claude Code skill definition.

Session context:
- Title: {title}
- Tools used: {tools}
- Original user intent: {intent}
- Session outcome: {outcome}

Generate a reusable skill. Output EXACTLY two sections:

SKILL_NAME: <kebab-case-name-under-50-chars>
SKILL_BODY:
<markdown instructions that tell Claude what to do when this skill is invoked>

The skill body should be 3-10 steps, actionable, and tool-specific where relevant.
"""


def slugify_skill_name(title: str) -> str:
    """Convert a session title to a valid kebab-case skill filename slug."""
    slug = title.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:60] or "untitled-skill"


def extract_session_skill_data(path: Path) -> dict:
    """Deep scan JSONL to extract tools used, first user message, last assistant message, title."""
    tools_used: set[str] = set()
    first_user_message: str | None = None
    last_assistant_message: str | None = None
    title = ""

    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = entry.get("type", "")
            if t == "assistant":
                for block in entry.get("message", {}).get("content", []):
                    if isinstance(block, dict):
                        if block.get("type") == "tool_use":
                            name = block.get("name", "")
                            if name:
                                tools_used.add(name)
                        elif block.get("type") == "text":
                            last_assistant_message = block.get("text", "")[:500]
            elif t == "user":
                content = entry.get("message", {}).get("content", "")
                if isinstance(content, str) and not first_user_message:
                    first_user_message = content[:500]
            elif t == "summary":
                title = entry.get("summary", "")
    except OSError:
        pass

    return {
        "tools_used": sorted(tools_used),
        "first_user_message": first_user_message or "",
        "last_assistant_message": last_assistant_message or "",
        "title": title,
    }


def resolve_skill_path(name: str, scope: str) -> Path:
    """Return a non-conflicting path for the skill file, auto-incrementing suffix if needed."""
    base_dir = (Path.cwd() / ".claude" / "skills") if scope == "local" else SKILLS_DIR
    base_dir.mkdir(parents=True, exist_ok=True)
    path = base_dir / f"{name}.md"
    counter = 2
    while path.exists():
        path = base_dir / f"{name}-{counter}.md"
        counter += 1
    return path


def ollama_generate_skill(skill_data: dict) -> tuple[str, str]:
    """Call Ollama to generate a skill name and body. Returns (name, body)."""
    prompt = SKILL_PROMPT_TEMPLATE.format(
        title=skill_data["title"],
        tools=", ".join(skill_data["tools_used"]) or "none",
        intent=skill_data["first_user_message"],
        outcome=skill_data["last_assistant_message"],
    )
    payload = json.dumps({"model": SUMMARY_MODEL, "prompt": prompt, "stream": False}).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        text = json.loads(resp.read()).get("response", "")
    name_match = re.search(r"SKILL_NAME:\s*(.+)", text)
    body_match = re.search(r"SKILL_BODY:\s*\n([\s\S]+)", text)
    name = slugify_skill_name(name_match.group(1).strip() if name_match else skill_data["title"])
    body = body_match.group(1).strip() if body_match else text.strip()
    return name, body


def template_generate_skill(skill_data: dict) -> tuple[str, str]:
    """Fallback skill generator when Ollama is unavailable."""
    name = slugify_skill_name(skill_data["title"])
    tools_str = "\n".join(f"- {t}" for t in skill_data["tools_used"]) or "- (no tools recorded)"
    body = (
        f"Replicate the workflow from a session titled: {skill_data['title']}\n\n"
        f"Original intent: {skill_data['first_user_message']}\n\n"
        f"Tools used in the original session:\n{tools_str}\n\n"
        "Steps:\n"
        "1. Understand the user's goal in context\n"
        "2. Apply the tools above as appropriate\n"
        "3. Confirm the outcome matches the original intent\n"
    )
    return name, body


# ─── Memory Explorer helpers ─────────────────────────────────────────────────


def validate_memory_path(rel_path: str) -> Path:
    """Resolve rel_path relative to CLAUDE_BASE_DIR. Raises HTTPException 403 if unsafe.

    Security: rejects null bytes, paths outside CLAUDE_BASE_DIR, paths outside the
    specific allowed subdirectory (prevents traversal like 'memory/../secrets.db'),
    and paths whose root component is not in the allowlist.
    """
    if "\x00" in rel_path:
        raise HTTPException(status_code=403, detail="Invalid path")

    parts = Path(rel_path).parts
    if not parts:
        raise HTTPException(status_code=403, detail="Empty path")

    root = parts[0]
    if root not in MEMORY_ALLOWLIST and rel_path not in MEMORY_ALLOWLIST_FILES:
        raise HTTPException(status_code=403, detail="Directory not allowed")

    try:
        resolved = (CLAUDE_BASE_DIR / rel_path).resolve()
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=403, detail="Invalid path") from exc

    # For top-level allowlisted files (e.g. "settings.json"), verify they stay within
    # CLAUDE_BASE_DIR.  For directory-rooted paths (e.g. "memory/…"), verify the
    # resolved path stays strictly inside that specific subdirectory so that a path
    # like "memory/../claude-sessions-ui.db" is rejected even though its parts[0] is
    # "memory" and the resolved target would still be inside CLAUDE_BASE_DIR.
    if rel_path in MEMORY_ALLOWLIST_FILES:
        allowed_base = CLAUDE_BASE_DIR.resolve()
    else:
        allowed_base = (CLAUDE_BASE_DIR / root).resolve()

    allowed_base_str = str(allowed_base)
    resolved_str = str(resolved)

    if resolved_str != allowed_base_str and not resolved_str.startswith(allowed_base_str + "/"):
        raise HTTPException(status_code=403, detail="Path traversal detected")

    return resolved


# ─── HTTP endpoints ──────────────────────────────────────────────────────────

@app.get("/api/sessions")
async def list_sessions(time_range: str = "1d"):
    if time_range not in TIME_RANGE_HOURS:
        time_range = "1d"
    hours = TIME_RANGE_HOURS[time_range]
    sess = get_sessions_for_range(time_range)
    stats = compute_global_stats(sess, hours if hours is not None else LIVE_HOURS)
    _update_prometheus(stats)
    # Only upsert when sessions came from JSONL (live path); historical DB reads
    # don't need to be written back and would add unnecessary write contention.
    # Reuse a single in-flight task to avoid queuing unbounded concurrent upserts.
    global _list_upsert_task
    if hours is not None and hours <= LIVE_HOURS and (_list_upsert_task is None or _list_upsert_task.done()):
        _list_upsert_task = asyncio.create_task(_upsert_in_background(sess))
    return {
        "sessions": sess,
        "stats": stats,
        "savings": compute_ollama_savings(),
        "truncation": compute_truncation_savings(),
        "time_range": time_range,
    }


@app.get("/api/projects")
async def get_projects(time_range: str = "1d"):
    if time_range not in TIME_RANGE_HOURS:
        time_range = "1d"
    sessions = get_sessions_for_range(time_range)
    return compute_project_stats(sessions)


def parse_trend_range(r: str) -> int:
    mapping = {"2w": 14, "4w": 28, "3m": 90}
    return mapping.get(r, 28)


@app.get("/api/trends")
async def get_trends(range: str = "4w"):
    days = parse_trend_range(range)
    from datetime import date as date_type

    cutoff = (date_type.today() - timedelta(days=days)).isoformat()

    def _query():
        with get_db() as conn:
            return conn.execute(
                "SELECT date, total_cost_usd, model_breakdown, session_count "
                "FROM daily_costs WHERE date >= ? ORDER BY date",
                (cutoff,),
            ).fetchall()

    rows = await asyncio.get_running_loop().run_in_executor(None, _query)
    config = read_config()
    days_data = [
        {
            "date": r[0],
            "total_cost_usd": r[1],
            "by_model": json.loads(r[2] or "{}"),
            "session_count": r[3],
        }
        for r in rows
    ]
    return {
        "days": days_data,
        "daily_budget_usd": config.get("daily_budget_usd"),
        "weekly_budget_usd": config.get("weekly_budget_usd"),
    }


@app.get("/api/config")
async def get_config():
    return read_config()


@app.put("/api/config")
async def put_config(body: dict):
    allowed_keys = {"daily_budget_usd", "weekly_budget_usd"}
    config = read_config()
    for k, v in body.items():
        if k in allowed_keys:
            config[k] = float(v) if v is not None else None
    write_config(config)
    return config


@app.get("/api/db/status")
async def db_status():
    if _db_conn is None:
        return {"total_stored": 0, "oldest": None, "newest": None, "db_path": str(DB_PATH)}
    with _db_lock:
        cur = _db_conn.execute("SELECT COUNT(*), MIN(last_active), MAX(last_active) FROM sessions")
        count, oldest, newest = cur.fetchone()
    return {"total_stored": count, "oldest": oldest, "newest": newest, "db_path": str(DB_PATH)}


@app.get("/api/ollama")
async def ollama_status():
    available = ollama_is_available()
    model_ready = ollama_model_pulled(SUMMARY_MODEL) if available else False
    return {
        "available": available,
        "model": SUMMARY_MODEL,
        "model_ready": model_ready,
        "url": OLLAMA_URL,
    }


@app.post("/api/sessions/{session_id}/summarize")
async def summarize_session(session_id: str):
    # Return cached summary if we have it
    cached = get_cached_summary(session_id)
    if cached:
        return {"session_id": session_id, "summary": cached, "cached": True}

    # Find the session to get its title text — check SQLite first so historical
    # sessions (older than LIVE_HOURS) can be summarized without a 404.
    loop = asyncio.get_running_loop()
    session = await loop.run_in_executor(None, get_session_by_id, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    raw_title = session.get("title", "")
    if not raw_title:
        return {"session_id": session_id, "summary": None, "cached": False}

    # Run Ollama in a thread so we don't block the event loop
    summary = await loop.run_in_executor(None, ollama_summarize, raw_title)

    if summary:
        cache_summary(session_id, summary)
    return {"session_id": session_id, "summary": summary, "cached": False}


@app.get("/api/sessions/{session_id}/detail")
async def session_detail(session_id: str, offset: int = 0, limit: int = 200):
    path = find_session_file(session_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Session not found")
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, parse_session_detail, path, offset, limit)
    return result


def render_transcript(path: Path) -> str:
    """Render all messages from a session JSONL as a readable markdown transcript."""
    session_id = path.stem
    result = parse_session_detail(path, offset=0, limit=999_999)
    messages = result["messages"]
    total = result["total_messages"]
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    lines: list[str] = [
        f"# Claude Session — {session_id[:8]}",
        "",
        f"**Session ID:** `{session_id}`  ",
        f"**Exported:** {now}  ",
        f"**Messages:** {total}",
        "",
        "---",
        "",
    ]

    for msg in messages:
        ts = ""
        if msg.get("timestamp"):
            with contextlib.suppress(ValueError):
                ts = f" · {datetime.fromisoformat(msg['timestamp'].replace('Z', '+00:00')).strftime('%H:%M:%S')}"

        mtype = msg.get("type", "")

        if mtype == "user":
            lines += [f"### You{ts}", "", msg.get("content", ""), "", "---", ""]
        elif mtype == "assistant":
            if msg.get("thinking"):
                lines += [
                    f"### Claude{ts}",
                    "",
                    "<details><summary>Extended thinking</summary>",
                    "",
                    msg["thinking"],
                    "",
                    "</details>",
                    "",
                    msg.get("content", ""),
                    "",
                    "---",
                    "",
                ]
            else:
                lines += [f"### Claude{ts}", "", msg.get("content", ""), "", "---", ""]
        elif mtype == "tool_use":
            tool = msg.get("tool_name") or "unknown"
            lines += [
                f"#### Tool: {tool}{ts}",
                "",
                "```",
                msg.get("content", ""),
                "```",
                "",
            ]
        elif mtype == "tool_result":
            tool = msg.get("tool_name") or "unknown"
            lines += [
                f"#### Result: {tool}",
                "",
                "```",
                msg.get("content", ""),
                "```",
                "",
            ]
        elif mtype == "summary":
            lines += [f"> **Summary:** {msg.get('content', '')}", ""]

    return "\n".join(lines)


@app.get("/api/sessions/{session_id}/transcript")
async def session_transcript(session_id: str):
    path = find_session_file(session_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Session not found")
    loop = asyncio.get_running_loop()
    text = await loop.run_in_executor(None, render_transcript, path)
    filename = f"claude-session-{session_id[:8]}.md"
    return PlainTextResponse(
        text,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/sessions/{session_id}/analytics")
async def get_session_analytics(session_id: str):
    if not re.match(r"^[a-zA-Z0-9_-]+$", session_id):
        raise HTTPException(status_code=400, detail="Invalid session ID")
    data = await parse_session_analytics(session_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return data


@app.post("/api/sessions/{session_id}/export-skill")
async def export_skill(session_id: str, scope: str = "global"):
    if scope not in ("global", "local"):
        scope = "global"
    path = find_session_file(session_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Session not found")
    loop = asyncio.get_running_loop()
    skill_data = await loop.run_in_executor(None, extract_session_skill_data, path)
    ollama_used = False
    try:
        available = await loop.run_in_executor(None, ollama_is_available)
        model_ready = (
            await loop.run_in_executor(None, ollama_model_pulled, SUMMARY_MODEL) if available else False
        )
        if not model_ready:
            raise RuntimeError("Ollama not ready")
        name, body = await loop.run_in_executor(None, ollama_generate_skill, skill_data)
        ollama_used = True
    except Exception:
        name, body = template_generate_skill(skill_data)
    skill_path = resolve_skill_path(name, scope)
    frontmatter = f"---\nname: {name}\ndescription: {skill_data['title']}\n---\n\n"
    skill_path.write_text(frontmatter + body, encoding="utf-8")
    return {
        "skill_name": name,
        "skill_path": str(skill_path),
        "scope": scope,
        "ollama_used": ollama_used,
    }


@app.get("/api/memory")
async def get_memory_tree():
    def _build_tree() -> dict:
        base = CLAUDE_BASE_DIR.resolve()
        tree: dict = {"type": "dir", "name": ".claude", "children": []}

        for fname in MEMORY_ALLOWLIST_FILES:
            fp = base / fname
            if fp.exists() and fp.is_file() and not fp.is_symlink():
                try:
                    stat = fp.stat()
                    tree["children"].append({
                        "type": "file",
                        "name": fname,
                        "path": fname,
                        "size": stat.st_size,
                        "mtime": stat.st_mtime,
                    })
                except OSError:
                    pass

        for dname in MEMORY_ALLOWLIST:
            dp = base / dname
            if dp.exists() and dp.is_dir() and not dp.is_symlink():
                tree["children"].append(_build_dir(dp, dname))

        return tree

    def _build_dir(directory: Path, rel_prefix: str) -> dict:
        children = []
        try:
            for entry in sorted(directory.iterdir(), key=lambda e: e.name):
                if entry.is_symlink():
                    continue
                rel = f"{rel_prefix}/{entry.name}"
                if entry.is_file():
                    try:
                        stat = entry.stat()
                        children.append({
                            "type": "file",
                            "name": entry.name,
                            "path": rel,
                            "size": stat.st_size,
                            "mtime": stat.st_mtime,
                        })
                    except OSError:
                        pass
                elif entry.is_dir() and not entry.name.startswith("."):
                    children.append(_build_dir(entry, rel))
        except PermissionError:
            pass
        return {"type": "dir", "name": directory.name, "path": rel_prefix, "children": children}

    result = await asyncio.get_running_loop().run_in_executor(None, _build_tree)
    return result


@app.get("/api/memory/file")
async def get_memory_file(path: str):
    resolved = validate_memory_path(path)

    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    MAX_SIZE = 500 * 1024
    try:
        stat = resolved.stat()
    except OSError as exc:
        raise HTTPException(status_code=404, detail="File not found") from exc

    truncated = stat.st_size > MAX_SIZE

    try:
        content = resolved.read_bytes()[:MAX_SIZE].decode("utf-8", errors="replace")
    except OSError as exc:
        raise HTTPException(status_code=404, detail="Cannot read file") from exc

    suffix = resolved.suffix.lower()
    if suffix in (".md", ".markdown"):
        mime = "text/markdown"
    elif suffix == ".json":
        mime = "application/json"
    else:
        mime = "text/plain"

    return {
        "path": path,
        "name": resolved.name,
        "content": content,
        "mime": mime,
        "size": stat.st_size,
        "mtime": stat.st_mtime,
        "truncated": truncated,
    }


@app.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics():
    # Trigger a refresh so metrics are fresh
    sess = get_all_sessions()
    stats = compute_global_stats(sess, LIVE_HOURS)
    _update_prometheus(stats)
    return PlainTextResponse(
        generate_latest().decode("utf-8"), media_type=CONTENT_TYPE_LATEST
    )


# ─── WebSocket ────────────────────────────────────────────────────────────────

_active_ws: list[WebSocket] = []
_list_upsert_task: asyncio.Task | None = None


@app.websocket("/ws")
async def websocket_endpoint(
    ws: WebSocket,
    time_range: str = "1d",
    start: str | None = None,
    end: str | None = None,
    project: str | None = None,
):
    # Validate custom date params before accepting
    if start:
        try:
            datetime.fromisoformat(start)
        except ValueError:
            await ws.close(code=1008, reason="Invalid start date")
            return
    if end:
        try:
            datetime.fromisoformat(end)
        except ValueError:
            await ws.close(code=1008, reason="Invalid end date")
            return

    if time_range not in TIME_RANGE_HOURS:
        time_range = "1d"
    await ws.accept()
    _active_ws.append(ws)
    upsert_task: asyncio.Task | None = None  # per-connection handle prevents backlog buildup
    try:
        while True:
            sess = get_sessions_for_range(time_range, start=start, end=end)
            if project:
                sess = [s for s in sess if s.get("project_name") == project]
            hours = TIME_RANGE_HOURS.get(time_range)
            stats = compute_global_stats(sess, hours if hours is not None else LIVE_HOURS)
            _update_prometheus(stats)
            # Only upsert for live JSONL ranges; skip a new upsert if the previous one is
            # still running to prevent an unbounded backlog of write tasks.
            if hours is not None and hours <= LIVE_HOURS and (upsert_task is None or upsert_task.done()):
                upsert_task = asyncio.create_task(_upsert_in_background(sess))
            await ws.send_json({
                "sessions": sess,
                "stats": stats,
                "savings": compute_ollama_savings(),
                "truncation": compute_truncation_savings(),
                "time_range": time_range,
            })
            # Live ranges poll fast; historical/all/custom ranges poll slower
            if hours is not None and hours <= LIVE_HOURS:
                interval = 2
            elif start or end or hours is None:
                interval = 30
            else:
                interval = 10
            await asyncio.sleep(interval)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if ws in _active_ws:
            _active_ws.remove(ws)


# ─── Serve built frontend ────────────────────────────────────────────────────

_frontend_dist = Path(__file__).parent / "frontend" / "dist"
if _frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="static")


if __name__ == "__main__":

    import uvicorn

    LOG_FILE = str(Path.home() / ".claude" / "claude-sessions-ui.log")
    log_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "()": "uvicorn.logging.DefaultFormatter",
                "fmt": "%(asctime)s %(levelprefix)s %(message)s",
            }
        },
        "handlers": {
            "file": {
                "class": "logging.FileHandler",
                "filename": LOG_FILE,
                "formatter": "default",
            }
        },
        "loggers": {
            "uvicorn": {"handlers": ["file"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"handlers": ["file"], "level": "INFO", "propagate": False},
            "uvicorn.access": {"handlers": ["file"], "level": "INFO", "propagate": False},
        },
    }
    uvicorn.run(app, host="0.0.0.0", port=8765, reload=False, log_config=log_config)
