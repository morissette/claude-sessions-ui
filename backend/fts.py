"""Full-text search helpers for Claude Sessions UI backend."""

import asyncio
import json
import logging
from datetime import datetime

from . import constants, database

logger = logging.getLogger(__name__)

# ─── Full-text search helpers ─────────────────────────────────────────────────

_fts_backfill_running: bool = False


async def backfill_fts() -> None:
    """Asynchronously populate session_messages FTS table from all JSONL files."""
    global _fts_backfill_running
    _fts_backfill_running = True
    try:
        def _run() -> None:
            # Phase 1 (outside lock): read all JSONL files — disk I/O must not hold _db_lock.
            jsonl_files = list(constants.CLAUDE_DIR.rglob("*.jsonl"))
            prefetched: dict[str, list[tuple[str, str, str, str]]] = {}
            for jf in jsonl_files:
                sid = jf.stem
                prefetched[sid] = database._extract_messages_from_jsonl(jf)

            # Phase 2 (inside lock): check existence + batch-insert only new sessions.
            with database._db_lock:
                if database._db_conn is None:
                    return
                rows_to_insert: list[tuple[str, str, str, str]] = []
                for sid, rows in prefetched.items():
                    if not rows:
                        continue
                    existing = database._db_conn.execute(
                        "SELECT 1 FROM session_messages WHERE session_id = ? LIMIT 1", (sid,)
                    ).fetchone()
                    if existing:
                        continue
                    rows_to_insert.extend(rows)
                if rows_to_insert:
                    database._db_conn.executemany(
                        "INSERT INTO session_messages (session_id, role, content, ts)"
                        " VALUES (?, ?, ?, ?)",
                        rows_to_insert,
                    )
                    database._db_conn.commit()

        await asyncio.get_running_loop().run_in_executor(None, _run)
        logger.info("FTS backfill complete")
    except Exception:
        logger.exception("FTS backfill failed")
    finally:
        _fts_backfill_running = False


async def search_fts(query: str, cutoff: datetime | None, limit: int) -> list[dict]:
    """Search session_messages FTS5 table for messages matching query.

    cutoff: if provided, only return results with last_active >= cutoff.
    Pass None for unbounded search (e.g. time_range="all").
    """

    def _query_db() -> list:
        try:
            with database._db_lock:
                if database._db_conn is None:
                    return []
                # JOIN sessions to fetch project_name/title in the same query,
                # avoiding an N+1 per-row lookup. bm25() is the correct FTS5
                # ranking function; the bare `rank` column does not exist on
                # FTS5 tables and raises OperationalError at runtime.
                if cutoff is not None:
                    sql = """
                        SELECT sm.session_id, sm.role, sm.ts,
                               snippet(session_messages, 2, '**', '**', '...', 16) AS snip,
                               bm25(session_messages),
                               s.project_name, s.title
                        FROM session_messages sm
                        JOIN sessions s ON sm.session_id = s.session_id
                        WHERE session_messages MATCH ?
                          AND s.last_active >= ?
                        ORDER BY bm25(session_messages)
                        LIMIT ?
                    """
                    params = (query, cutoff.isoformat(), limit)
                else:
                    sql = """
                        SELECT sm.session_id, sm.role, sm.ts,
                               snippet(session_messages, 2, '**', '**', '...', 16) AS snip,
                               bm25(session_messages),
                               s.project_name, s.title
                        FROM session_messages sm
                        JOIN sessions s ON sm.session_id = s.session_id
                        WHERE session_messages MATCH ?
                        ORDER BY bm25(session_messages)
                        LIMIT ?
                    """
                    params = (query, limit)
                rows = database._db_conn.execute(sql, params).fetchall()
            return list(rows)
        except Exception:
            return []

    rows = await asyncio.get_running_loop().run_in_executor(None, _query_db)
    results: list[dict] = []
    for sid, role, ts, snip, score, project_name, session_title in rows:
        results.append({
            "session_id": sid,
            "project_name": project_name or "",
            "session_title": session_title or "",
            "role": role,
            "snippet": snip or "",
            "ts": ts,
            "score": score or 0.0,
        })
    return results


async def search_jsonl_live(query: str, cutoff: datetime, limit: int) -> list[dict]:
    """Scan live JSONL files for messages containing the query string."""

    def _scan() -> list[dict]:
        results: list[dict] = []
        q_lower = query.lower()
        cutoff_ts = cutoff.timestamp()
        for jf in constants.CLAUDE_DIR.rglob("*.jsonl"):
            try:
                if jf.stat().st_mtime < cutoff_ts:
                    continue
            except OSError:
                continue
            if len(results) >= limit:
                break
            sid = jf.stem
            try:
                with open(jf, encoding="utf-8", errors="replace") as f:
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
                        raw = msg.get("content", "")
                        if isinstance(raw, str):
                            content = raw
                        elif isinstance(raw, list):
                            for block in raw:
                                if isinstance(block, dict) and block.get("type") == "text":
                                    content += block.get("text", "") + " "
                        if q_lower in content.lower():
                            idx = content.lower().find(q_lower)
                            start = max(0, idx - 50)
                            end = min(len(content), idx + len(query) + 50)
                            snippet = content[start:end]
                            results.append({
                                "session_id": sid,
                                "project_name": str(jf.parent.name),
                                "session_title": sid[:20],
                                "role": role,
                                "snippet": f"...{snippet}...",
                                "ts": entry.get("timestamp", ""),
                                "score": 1.0,
                            })
                            if len(results) >= limit:
                                break
            except OSError:
                continue
        return results

    return await asyncio.get_running_loop().run_in_executor(None, _scan)
