"""System/infrastructure HTTP endpoints."""

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest  # noqa: F401

from backend import aggregation, constants, database, metrics, ollama

router = APIRouter()


@router.get("/api/db/status")
async def db_status():
    if database._db_conn is None:
        return {"total_stored": 0, "oldest": None, "newest": None, "db_path": str(constants.DB_PATH)}
    with database._db_lock:
        cur = database._db_conn.execute(
            "SELECT COUNT(*), MIN(last_active), MAX(last_active) FROM sessions"
        )
        count, oldest, newest = cur.fetchone()
    return {"total_stored": count, "oldest": oldest, "newest": newest, "db_path": str(constants.DB_PATH)}


@router.get("/api/ollama")
async def ollama_status():
    available = ollama.ollama_is_available()
    model_ready = ollama.ollama_model_pulled(constants.SUMMARY_MODEL) if available else False
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
