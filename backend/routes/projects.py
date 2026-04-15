"""Project-related HTTP endpoints."""

import asyncio
import json
from datetime import date as date_type
from datetime import timedelta

from fastapi import APIRouter

from backend import aggregation, config, constants, database

router = APIRouter()


def _parse_trend_range(r: str) -> int:
    mapping = {"2w": 14, "4w": 28, "3m": 90}
    return mapping.get(r, 28)


@router.get("/api/projects")
async def get_projects(time_range: str = "1d"):
    if time_range not in constants.TIME_RANGE_HOURS:
        time_range = "1d"
    sessions = aggregation.get_sessions_for_range(time_range)
    return aggregation.compute_project_stats(sessions)


@router.get("/api/trends")
async def get_trends(range: str = "4w"):
    days = _parse_trend_range(range)
    cutoff = (date_type.today() - timedelta(days=days)).isoformat()

    def _query():
        with database.get_db() as conn:
            return conn.execute(
                "SELECT date, total_cost_usd, model_breakdown, session_count "
                "FROM daily_costs WHERE date >= ? ORDER BY date",
                (cutoff,),
            ).fetchall()

    rows = await asyncio.get_running_loop().run_in_executor(None, _query)
    cfg = config.read_config()
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
        "daily_budget_usd": cfg.get("daily_budget_usd"),
        "weekly_budget_usd": cfg.get("weekly_budget_usd"),
    }
