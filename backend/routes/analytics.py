"""Analytics endpoint for Claude Sessions UI."""

import asyncio
from collections import Counter
from datetime import datetime

from fastapi import APIRouter

from .. import aggregation, constants

router = APIRouter()


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(constants._normalize_ts(ts))
    except (ValueError, TypeError):
        return None


def _session_stub(s: dict, **extra) -> dict:
    return {
        "session_id": s["session_id"],
        "title": s.get("title") or s["session_id"][:16],
        "project_name": s.get("project_name") or "unknown",
        **extra,
    }


# ─── Analytics computation ────────────────────────────────────────────────────


def _compute_analytics(sessions: list[dict], tool_usage: list[dict]) -> dict:
    if not sessions:
        return _empty_response(tool_usage)

    # ── Durations ────────────────────────────────────────────────────────────
    durations: list[tuple[dict, float]] = []
    for s in sessions:
        sa = _parse_ts(s.get("started_at"))
        la = _parse_ts(s.get("last_active"))
        if sa and la:
            delta = (la - sa).total_seconds()
            if delta > 0:
                durations.append((s, delta))

    total_wall_time_s = sum(d for _, d in durations)

    # ── Token / cost aggregates ───────────────────────────────────────────────
    total_output_tokens = sum(s["stats"].get("output_tokens", 0) for s in sessions)
    total_turns = sum(s.get("turns", 0) for s in sessions)
    total_cost = sum(s["stats"].get("estimated_cost_usd", 0.0) for s in sessions)
    total_tokens = sum(s["stats"].get("total_tokens", 0) for s in sessions)

    avg_cost_per_turn = round(total_cost / total_turns, 6) if total_turns else 0.0
    avg_tokens_per_turn = round(total_tokens / total_turns, 1) if total_turns else 0.0

    # ── Cache efficiency ──────────────────────────────────────────────────────
    cache_read = sum(s["stats"].get("cache_read_tokens", 0) for s in sessions)
    cache_create = sum(s["stats"].get("cache_create_tokens", 0) for s in sessions)
    cache_denom = cache_read + cache_create
    cache_efficiency_pct = round(cache_read / cache_denom * 100, 1) if cache_denom else 0.0

    # ── Cache savings in USD (per-model pricing) ──────────────────────────────
    cache_savings_usd = 0.0
    for s in sessions:
        model = s.get("model") or "default"
        pricing = constants.MODEL_PRICING.get(model, constants.MODEL_PRICING["default"])
        rate_diff = (pricing["input"] - pricing["cache_read"]) / 1_000_000
        cache_savings_usd += s["stats"].get("cache_read_tokens", 0) * rate_diff
    cache_savings_usd = round(cache_savings_usd, 4)

    # ── Ranked session lists ──────────────────────────────────────────────────
    # Build a duration lookup by session identity for O(n) access
    dur_map: dict[int, float] = {id(s): d for s, d in durations}

    longest_sessions = [
        _session_stub(s,
                      duration_seconds=d,
                      cost_usd=round(s["stats"].get("estimated_cost_usd", 0.0), 4))
        for s, d in sorted(durations, key=lambda x: x[1], reverse=True)[:5]
    ]

    most_expensive_sessions = [
        _session_stub(s,
                      cost_usd=round(s["stats"].get("estimated_cost_usd", 0.0), 4),
                      duration_seconds=dur_map.get(id(s), 0))
        for s in sorted(sessions,
                        key=lambda s: s["stats"].get("estimated_cost_usd", 0.0),
                        reverse=True)[:5]
    ]

    most_turns_sessions = [
        _session_stub(s,
                      turns=s.get("turns", 0),
                      cost_usd=round(s["stats"].get("estimated_cost_usd", 0.0), 4))
        for s in sorted(sessions, key=lambda s: s.get("turns", 0), reverse=True)[:5]
    ]

    subagent_sessions = [s for s in sessions if s.get("subagent_count", 0) > 0]
    most_subagents_sessions = [
        _session_stub(s, subagent_count=s["subagent_count"])
        for s in sorted(subagent_sessions,
                        key=lambda s: s["subagent_count"],
                        reverse=True)[:5]
    ]

    # ── Project aggregations ──────────────────────────────────────────────────
    projects: dict[str, dict] = {}
    for s in sessions:
        key = s.get("project_path") or s.get("project_name") or "unknown"
        if key not in projects:
            projects[key] = {
                "project_name": s.get("project_name") or "unknown",
                "session_count": 0,
                "total_cost_usd": 0.0,
            }
        projects[key]["session_count"] += 1
        projects[key]["total_cost_usd"] += s["stats"].get("estimated_cost_usd", 0.0)

    proj_list = list(projects.values())
    projects_by_sessions = [
        {"project_name": p["project_name"], "session_count": p["session_count"],
         "total_cost_usd": round(p["total_cost_usd"], 4)}
        for p in sorted(proj_list, key=lambda p: p["session_count"], reverse=True)[:10]
    ]
    projects_by_cost = [
        {"project_name": p["project_name"], "session_count": p["session_count"],
         "total_cost_usd": round(p["total_cost_usd"], 4)}
        for p in sorted(proj_list, key=lambda p: p["total_cost_usd"], reverse=True)[:10]
    ]

    # ── Model distribution ────────────────────────────────────────────────────
    by_model: dict[str, dict] = {}
    for s in sessions:
        m = s.get("model") or "unknown"
        if m not in by_model:
            by_model[m] = {"session_count": 0, "total_cost_usd": 0.0}
        by_model[m]["session_count"] += 1
        by_model[m]["total_cost_usd"] += s["stats"].get("estimated_cost_usd", 0.0)

    n = len(sessions)
    model_distribution = [
        {
            "model": m,
            "session_count": d["session_count"],
            "total_cost_usd": round(d["total_cost_usd"], 4),
            "pct": round(d["session_count"] / n * 100, 1),
        }
        for m, d in sorted(by_model.items(),
                            key=lambda x: x[1]["total_cost_usd"],
                            reverse=True)
    ]

    # ── Active hours histogram ────────────────────────────────────────────────
    hour_counts: Counter = Counter()
    for s in sessions:
        dt = _parse_ts(s.get("started_at"))
        if dt:
            hour_counts[dt.hour] += 1
    active_hours = [{"hour": h, "count": hour_counts.get(h, 0)} for h in range(24)]

    return {
        "session_metrics": {
            "total_wall_time_seconds": int(total_wall_time_s),
            "estimated_time_saved_hours": round(total_output_tokens / 4_000, 1),
            "total_sessions": n,
            "sessions_with_duration": len(durations),
            "avg_cost_per_turn": avg_cost_per_turn,
            "avg_tokens_per_turn": avg_tokens_per_turn,
            "cache_efficiency_pct": cache_efficiency_pct,
            "cache_savings_usd": cache_savings_usd,
            "longest_sessions": longest_sessions,
            "most_expensive_sessions": most_expensive_sessions,
            "most_turns_sessions": most_turns_sessions,
            "most_subagents_sessions": most_subagents_sessions,
            "projects_by_sessions": projects_by_sessions,
            "projects_by_cost": projects_by_cost,
            "model_distribution": model_distribution,
            "active_hours": active_hours,
            "top_tools": tool_usage,
        }
    }


def _empty_response(tool_usage: list[dict]) -> dict:
    return {
        "session_metrics": {
            "total_wall_time_seconds": 0,
            "estimated_time_saved_hours": 0.0,
            "total_sessions": 0,
            "sessions_with_duration": 0,
            "avg_cost_per_turn": 0.0,
            "avg_tokens_per_turn": 0.0,
            "cache_efficiency_pct": 0.0,
            "cache_savings_usd": 0.0,
            "longest_sessions": [],
            "most_expensive_sessions": [],
            "most_turns_sessions": [],
            "most_subagents_sessions": [],
            "projects_by_sessions": [],
            "projects_by_cost": [],
            "model_distribution": [],
            "active_hours": [{"hour": h, "count": 0} for h in range(24)],
            "top_tools": tool_usage,
        }
    }


# ─── Route ───────────────────────────────────────────────────────────────────


@router.get("/api/analytics")
async def get_analytics(
    time_range: str = "1d",
    start: str | None = None,
    end: str | None = None,
):
    # Custom date range: validate ISO strings, delegate to SQLite
    if start or end:
        from datetime import datetime  # noqa: PLC0415
        for label, val in (("start", start), ("end", end)):
            if val:
                try:
                    datetime.fromisoformat(constants._normalize_ts(val))
                except ValueError as exc:
                    from fastapi import HTTPException  # noqa: PLC0415
                    raise HTTPException(status_code=422, detail=f"Invalid {label} date") from exc
    elif time_range not in constants.TIME_RANGE_HOURS:
        time_range = "1d"

    loop = asyncio.get_running_loop()
    sessions = await loop.run_in_executor(
        None, aggregation.get_sessions_for_range, time_range, start, end
    )
    tool_usage = await loop.run_in_executor(
        None, aggregation.get_global_tool_usage, sessions
    )
    return await loop.run_in_executor(None, _compute_analytics, sessions, tool_usage)
