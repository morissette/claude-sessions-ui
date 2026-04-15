"""FastAPI application object for Claude Sessions UI backend."""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import aggregation, constants, database, fts
from .routes import register_routes

logger = logging.getLogger(__name__)


async def _startup_backfill() -> None:
    """Asynchronously backfill all historical JSONL sessions into SQLite."""
    try:
        loop = asyncio.get_running_loop()
        sessions = await loop.run_in_executor(None, aggregation.get_all_sessions, None)
        await loop.run_in_executor(None, database.upsert_sessions_to_db, sessions)
        logger.info("Startup backfill complete: %d sessions stored", len(sessions))
    except Exception:
        logger.exception("Startup backfill failed")
    asyncio.create_task(fts.backfill_fts())


@asynccontextmanager
async def lifespan(_app: FastAPI):
    constants.SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)
    database.init_db()
    asyncio.create_task(_startup_backfill())
    asyncio.create_task(database.backfill_daily_costs())
    yield
    # Shutdown: acquire the lock so we don't race with in-flight upsert threads,
    # then close the connection to release file locks/descriptors.
    with database._db_lock:
        if database._db_conn is not None:
            database._db_conn.close()
            database._db_conn = None


app = FastAPI(title="Claude Sessions UI", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

register_routes(app)

# Static files mount MUST be last — catch-all would shadow API routes
_frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if _frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="static")
