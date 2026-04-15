"""Session-related HTTP endpoints."""

import asyncio
import io
import json
import logging
import re
import zipfile
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse, Response, StreamingResponse

from .. import (
    aggregation,
    constants,
    database,
    detail,
    fts,
    metrics,
    ollama,
    parsing,
    skills,
)

log = logging.getLogger(__name__)

router = APIRouter()


# ─── Helpers ─────────────────────────────────────────────────────────────────

async def _trigger_summary(session_id: str, jsonl_path) -> str | None:
    """Generate and cache an Ollama summary for a session."""
    cached = ollama.get_cached_summary(session_id)
    if cached:
        return cached
    loop = asyncio.get_running_loop()
    project_path = str(jsonl_path.parent)
    session = await loop.run_in_executor(None, parsing.parse_session_file, jsonl_path, project_path)
    if session is None:
        return None
    raw_title = session.get("title", "")
    if not raw_title:
        return None
    summary = await loop.run_in_executor(None, ollama.ollama_summarize, raw_title)
    if summary:
        ollama.cache_summary(session_id, summary)
    return summary


def _get_transcript_text(session_id: str) -> str | None:
    """Return rendered transcript text for a session ID, or None if not found."""
    path = detail.find_session_file(session_id)
    if path is None:
        return None
    return detail.render_transcript(path)


# ─── Routes ──────────────────────────────────────────────────────────────────

# Module-level task handle — prevents queuing unbounded concurrent upserts
_list_upsert_task: asyncio.Task | None = None


@router.get("/api/sessions")
async def list_sessions(time_range: str = "1d"):
    global _list_upsert_task
    if time_range not in constants.TIME_RANGE_HOURS:
        time_range = "1d"
    hours = constants.TIME_RANGE_HOURS[time_range]
    sess = aggregation.get_sessions_for_range(time_range)
    stats = aggregation.compute_global_stats(sess, hours if hours is not None else constants.LIVE_HOURS)
    metrics._update_prometheus(stats)
    if hours is not None and hours <= constants.LIVE_HOURS and (
        _list_upsert_task is None or _list_upsert_task.done()
    ):
        _list_upsert_task = asyncio.create_task(database._upsert_in_background(sess))
    return {
        "sessions": sess,
        "stats": stats,
        "savings": ollama.compute_ollama_savings(),
        "truncation": ollama.compute_truncation_savings(),
        "time_range": time_range,
    }


@router.get("/api/search")
async def search_sessions(q: str = "", time_range: str = "1d", limit: int = 20):
    q = q.strip()[:200]
    if not q:
        return {"query": q, "results": [], "total": 0, "index_ready": not fts._fts_backfill_running}

    limit = max(1, min(100, limit))
    hours = constants.TIME_RANGE_HOURS.get(time_range, 24)
    cutoff = None if hours is None else datetime.now(UTC) - timedelta(hours=hours)

    try:
        if hours is not None and hours <= constants.LIVE_HOURS:
            results = await fts.search_jsonl_live(q, cutoff, limit)
        else:
            results = await fts.search_fts(q, cutoff, limit)
    except Exception:
        log.exception("Search failed for query %r", q)
        results = []

    return {
        "query": q,
        "results": results[:limit],
        "total": len(results),
        "index_ready": not fts._fts_backfill_running,
    }


@router.post("/api/sessions/{session_id}/summarize")
async def summarize_session(session_id: str):
    cached = ollama.get_cached_summary(session_id)
    if cached:
        return {"session_id": session_id, "summary": cached, "cached": True}

    loop = asyncio.get_running_loop()
    session = await loop.run_in_executor(None, database.get_session_by_id, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    raw_title = session.get("title", "")
    if not raw_title:
        return {"session_id": session_id, "summary": None, "cached": False}

    summary = await loop.run_in_executor(None, ollama.ollama_summarize, raw_title)

    if summary:
        ollama.cache_summary(session_id, summary)
    return {"session_id": session_id, "summary": summary, "cached": False}


@router.get("/api/sessions/{session_id}/detail")
async def session_detail(session_id: str, offset: int = 0, limit: int = 200):
    path = detail.find_session_file(session_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Session not found")
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, detail.parse_session_detail, path, offset, limit)
    return result


@router.get("/api/sessions/{session_id}/transcript")
async def session_transcript(session_id: str):
    path = detail.find_session_file(session_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Session not found")
    loop = asyncio.get_running_loop()
    text = await loop.run_in_executor(None, detail.render_transcript, path)
    filename = f"claude-session-{session_id[:8]}.md"
    return PlainTextResponse(
        text,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/api/sessions/{session_id}/analytics")
async def get_session_analytics(session_id: str):
    if not re.match(r"^[a-zA-Z0-9_-]+$", session_id):
        raise HTTPException(status_code=400, detail="Invalid session ID")
    data = await detail.parse_session_analytics(session_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return data


@router.post("/api/sessions/{session_id}/export-skill")
async def export_skill(session_id: str, scope: str = "global"):
    if scope not in ("global", "local"):
        scope = "global"
    path = detail.find_session_file(session_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Session not found")
    loop = asyncio.get_running_loop()
    skill_data = await loop.run_in_executor(None, skills.extract_session_skill_data, path)
    ollama_used = False
    try:
        available = await loop.run_in_executor(None, ollama.ollama_is_available)
        model_ready = (
            await loop.run_in_executor(None, ollama.ollama_model_pulled, constants.SUMMARY_MODEL)
            if available
            else False
        )
        if not model_ready:
            raise RuntimeError("Ollama not ready")
        name, body = await loop.run_in_executor(None, skills.ollama_generate_skill, skill_data)
        ollama_used = True
    except Exception:
        name, body = skills.template_generate_skill(skill_data)
    skill_path = skills.resolve_skill_path(name, scope)
    # Sanitize title for YAML frontmatter: strip newlines and characters
    # that would break the inline scalar (colons, leading dashes/hashes).
    safe_title = re.sub(r"[\r\n]+", " ", skill_data["title"]).strip()
    safe_title = re.sub(r"[^\x20-\x7E]", "", safe_title)  # drop non-printable ASCII
    frontmatter = f"---\nname: {name}\ndescription: {safe_title!r}\n---\n\n"
    skill_path.write_text(frontmatter + body, encoding="utf-8")
    return {
        "skill_name": name,
        "skill_path": str(skill_path),
        "scope": scope,
        "ollama_used": ollama_used,
    }


# ─── Batch operations ─────────────────────────────────────────────────────────


@router.post("/api/batch/summarize")
async def batch_summarize(body: dict):
    import logging
    _logger = logging.getLogger(__name__)

    session_ids = body.get("session_ids", [])
    if not isinstance(session_ids, list):
        raise HTTPException(status_code=400, detail="session_ids must be a list")
    session_ids = session_ids[:50]
    if not session_ids:
        raise HTTPException(status_code=400, detail="No session IDs provided")
    for sid in session_ids:
        if not re.match(r"^[a-zA-Z0-9_-]+$", sid):
            raise HTTPException(status_code=400, detail=f"Invalid session ID: {sid}")

    async def generate():
        for sid in session_ids:
            yield f"data: {json.dumps({'id': sid, 'status': 'pending'})}\n\n"
            try:
                jf = detail.find_session_file(sid)
                if jf is None:
                    yield f"data: {json.dumps({'id': sid, 'status': 'error', 'error': 'session not found'})}\n\n"
                    continue
                result = await _trigger_summary(sid, jf)
                if result:
                    yield f"data: {json.dumps({'id': sid, 'status': 'done'})}\n\n"
                else:
                    yield f"data: {json.dumps({'id': sid, 'status': 'error', 'error': 'summary unavailable'})}\n\n"
            except Exception:
                _logger.exception("Batch summarize failed for session %s", sid)
                yield f"data: {json.dumps({'id': sid, 'status': 'error', 'error': 'summarization failed'})}\n\n"
        yield 'data: {"done": true}\n\n'

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/api/batch/export")
async def batch_export(body: dict):
    session_ids = body.get("session_ids", [])
    if not isinstance(session_ids, list):
        raise HTTPException(status_code=400, detail="session_ids must be a list")
    session_ids = session_ids[:100]
    if not session_ids:
        raise HTTPException(status_code=400, detail="No session IDs provided")
    for sid in session_ids:
        if not re.match(r"^[a-zA-Z0-9_-]+$", sid):
            raise HTTPException(status_code=400, detail=f"Invalid session ID: {sid}")

    def build_zip() -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for sid in session_ids:
                transcript = _get_transcript_text(sid)
                if transcript:
                    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", sid)
                    zf.writestr(f"{safe_name}.md", transcript)
        return buf.getvalue()

    zip_bytes = await asyncio.get_running_loop().run_in_executor(None, build_zip)
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=sessions-export.zip"},
    )


@router.post("/api/batch/cost-report")
async def batch_cost_report(body: dict):
    import csv

    session_ids = body.get("session_ids", [])
    if not isinstance(session_ids, list):
        raise HTTPException(status_code=400, detail="session_ids must be a list")
    session_ids = session_ids[:100]
    if not session_ids:
        raise HTTPException(status_code=400, detail="No session IDs provided")
    for sid in session_ids:
        if not re.match(r"^[a-zA-Z0-9_-]+$", sid):
            raise HTTPException(status_code=400, detail=f"Invalid session ID: {sid}")

    # Snapshot cache before entering thread pool to avoid concurrent modification
    cache_snapshot = dict(parsing._session_cache)

    def build_csv() -> str:
        found_sessions = []
        for sid in session_ids:
            for cache_entry in cache_snapshot.values():
                s = cache_entry[1]  # (mtime, session_data)
                if isinstance(s, dict) and s.get("session_id") == sid:
                    found_sessions.append(s)
                    break

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "session_id", "project_name", "title", "model",
            "started_at", "last_active", "turns",
            "input_tokens", "output_tokens", "cache_create_tokens", "cache_read_tokens",
            "total_tokens", "estimated_cost_usd",
        ])
        for s in found_sessions:
            stats = s.get("stats", {})
            writer.writerow([
                s["session_id"],
                s.get("project_name", ""),
                s.get("title", ""),
                s.get("model", ""),
                s.get("started_at", ""),
                s.get("last_active", ""),
                s.get("turns", 0),
                stats.get("input_tokens", 0),
                stats.get("output_tokens", 0),
                stats.get("cache_create_tokens", 0),
                stats.get("cache_read_tokens", 0),
                stats.get("total_tokens", 0),
                stats.get("estimated_cost_usd", 0.0),
            ])
        return buf.getvalue()

    csv_str = await asyncio.get_running_loop().run_in_executor(None, build_csv)
    return Response(
        content=csv_str.encode("utf-8"),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=cost-report.csv"},
    )
