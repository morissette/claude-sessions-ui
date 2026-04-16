"""Route registration for Claude Sessions UI backend."""

from .analytics import router as analytics_router
from .config import router as config_router
from .memory import router as memory_router
from .misc_stats import router as misc_stats_router
from .projects import router as projects_router
from .sessions import router as sessions_router
from .system import router as system_router
from .websocket import router as websocket_router


def register_routes(app) -> None:
    app.include_router(sessions_router)
    app.include_router(projects_router)
    app.include_router(analytics_router)
    app.include_router(misc_stats_router)
    app.include_router(config_router)
    app.include_router(memory_router)
    app.include_router(system_router)
    app.include_router(websocket_router)
