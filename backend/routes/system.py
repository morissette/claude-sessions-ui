"""System/infrastructure HTTP endpoints."""

import asyncio

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .. import aggregation, constants, database, metrics, ollama

router = APIRouter()


@router.get("/api/db/status")
async def db_status():
    def _query():
        if database._db_conn is None:
            return {"total_stored": 0, "oldest": None, "newest": None, "db_path": str(constants.DB_PATH)}
        with database._db_lock:
            cur = database._db_conn.execute(
                "SELECT COUNT(*), MIN(last_active), MAX(last_active) FROM sessions"
            )
            count, oldest, newest = cur.fetchone()
        return {"total_stored": count, "oldest": oldest, "newest": newest, "db_path": str(constants.DB_PATH)}

    return await asyncio.get_running_loop().run_in_executor(None, _query)


@router.get("/api/ollama")
async def ollama_status():
    loop = asyncio.get_running_loop()
    available = await loop.run_in_executor(None, ollama.ollama_is_available)
    model_ready = (
        await loop.run_in_executor(None, ollama.ollama_model_pulled, constants.SUMMARY_MODEL)
        if available else False
    )
    return {
        "available": available,
        "model": constants.SUMMARY_MODEL,
        "model_ready": model_ready,
        "url": constants.OLLAMA_URL,
    }


@router.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics():
    sess = aggregation.get_all_sessions()
    stats = aggregation.compute_global_stats(sess, constants.LIVE_HOURS)
    metrics._update_prometheus(stats)
    return PlainTextResponse(
        generate_latest().decode("utf-8"), media_type=CONTENT_TYPE_LATEST
    )
