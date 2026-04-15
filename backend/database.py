"""SQLite storage layer for Claude Sessions UI backend."""

import asyncio
import contextlib
import json
import logging
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import constants
from .detail import find_session_file
from .ollama import get_cached_summary
from .process import get_running_claude_processes

logger = logging.getLogger(__name__)

# ─── Module-level state ───────────────────────────────────────────────────────

_db_conn: sqlite3.Connection | None = None
_db_lock = threading.Lock()


# ─── SQLite storage ───────────────────────────────────────────────────────────

@contextlib.contextmanager
def get_db():
    """Yield the shared SQLite connection under the write lock."""
    with _db_lock:
        yield _db_conn


def init_db() -> None:
    """Create the SQLite DB, table, and indexes. Must be called once at startup."""
    global _db_conn
    constants.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if _db_conn is not None:
        _db_conn.close()
    _db_conn = sqlite3.connect(str(constants.DB_PATH), check_same_thread=False)
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
    # FTS5 virtual table for full-text search across session messages
    _db_conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS session_messages USING fts5(
            session_id UNINDEXED,
            role,
            content,
            ts UNINDEXED,
            tokenize = 'porter ascii'
        )
    """)
    _db_conn.commit()


def _extract_messages_from_jsonl(jsonl_path: Path) -> list[tuple[str, str, str, str]]:
    """Parse a JSONL file and return (session_id, role, content, ts) tuples for FTS indexing."""
    sid = jsonl_path.stem
    rows: list[tuple[str, str, str, str]] = []
    try:
        with open(jsonl_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = entry.get("message", {})
                role = msg.get("role") or entry.get("type", "")
                if role not in ("user", "assistant"):
                    continue
                content = ""
                raw_content = msg.get("content", "")
                if isinstance(raw_content, str):
                    content = raw_content
                elif isinstance(raw_content, list):
                    for block in raw_content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            content += block.get("text", "") + " "
                if not content.strip():
                    continue
                rows.append((sid, role, content[:4000], entry.get("timestamp", "")))
    except OSError:
        pass
    return rows


def _sync_fts(conn: sqlite3.Connection, session_id: str, jsonl_path: Path) -> None:
    """Re-index a single session's messages in the FTS5 table."""
    conn.execute("DELETE FROM session_messages WHERE session_id = ?", (session_id,))
    rows = _extract_messages_from_jsonl(jsonl_path)
    if rows:
        conn.executemany(
            "INSERT INTO session_messages (session_id, role, content, ts) VALUES (?, ?, ?, ?)",
            rows,
        )


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
            constants._normalize_ts(s["started_at"]),
            constants._normalize_ts(s["last_active"]),
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
                    affected_dates.add(constants._normalize_ts(started_at)[:10])  # "YYYY-MM-DD"
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
        # Keep the FTS index in sync so new/updated sessions are searchable
        # immediately without waiting for the next full backfill.
        for s in sessions:
            jsonl_path = find_session_file(s["session_id"])
            if jsonl_path is not None:
                _sync_fts(_db_conn, s["session_id"], jsonl_path)
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
    from backend.aggregation import get_all_sessions  # noqa: PLC0415 — avoids circular import

    hours = constants.TIME_RANGE_HOURS.get(time_range, 24)

    # Custom range always routes to SQLite
    if start or end:
        return get_sessions_from_db(start=start, end=end)

    # "all" routes to SQLite with no cutoff
    if hours is None:
        return get_sessions_from_db()

    # Existing routing logic unchanged
    if hours <= constants.LIVE_HOURS:
        return get_all_sessions(hours=hours)
    return get_sessions_from_db(hours=hours)


def get_all_sessions_unbounded() -> list[dict]:
    """Parse all JSONL sessions regardless of age — used for startup DB backfill."""
    from backend.aggregation import get_all_sessions  # noqa: PLC0415 — avoids circular import

    return get_all_sessions(hours=None)


def get_session_by_id(session_id: str) -> dict | None:
    """Return a single session dict by ID, checking SQLite first then JSONL fallback."""
    from backend.aggregation import get_all_sessions  # noqa: PLC0415 — avoids circular import

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


async def _upsert_in_background(sessions: list[dict]) -> None:
    """Run upsert_sessions_to_db in a thread pool, logging any error instead of dropping it."""
    try:
        await asyncio.get_running_loop().run_in_executor(None, upsert_sessions_to_db, sessions)
    except Exception:
        logger.exception("Background SQLite upsert failed")


async def backfill_daily_costs() -> None:
    """Recompute daily_costs table from all sessions data."""
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
