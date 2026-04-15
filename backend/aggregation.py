"""Session aggregation helpers for Claude Sessions UI backend."""

import logging
import time
from datetime import UTC, datetime, timedelta

from . import constants, database, ollama, parsing, process

logger = logging.getLogger(__name__)


# ─── Session aggregation ─────────────────────────────────────────────────────


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
        if started and p["first_session"] and constants._normalize_ts(started) < constants._normalize_ts(p["first_session"]):
            p["first_session"] = started
        if active and p["last_session"] and constants._normalize_ts(active) > constants._normalize_ts(p["last_session"]):
            p["last_session"] = active

    for p in projects.values():
        p["models"] = sorted(p["models"])

    return sorted(projects.values(), key=lambda p: p["total_cost_usd"], reverse=True)


def get_all_sessions(hours: int | None = 24) -> list[dict]:
    if not constants.CLAUDE_DIR.exists():
        return []

    processes = process.get_running_claude_processes()
    cwd_pids: dict[str, list[int]] = {}
    session_pid: dict[str, int] = {}

    for pid, info in processes.items():
        if info["cwd"]:
            cwd_pids.setdefault(info["cwd"], []).append(pid)
        if info["session_id"]:
            session_pid[info["session_id"]] = pid

    now = time.time()
    cutoff = (now - hours * 3600) if hours is not None else 0

    # Single pass: collect (session, cwd, mtime) tuples and build cwd_newest_mtime
    # simultaneously to avoid iterating the project directories twice.
    cwd_newest_mtime: dict[str, float] = {}
    collected: list[tuple[dict, str | None, float]] = []

    for project_dir in constants.CLAUDE_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        for jsonl_file in project_dir.glob("*.jsonl"):
            try:
                mtime = jsonl_file.stat().st_mtime
            except OSError:
                continue
            if mtime < cutoff:
                continue

            cwd = parsing.get_session_cwd(jsonl_file)
            project_path = cwd or ("/" + project_dir.name.lstrip("-"))

            session = parsing.parse_session_file(jsonl_file, project_path)
            if session is None:
                continue

            # Shallow copy so we can annotate is_active/pid/summary without dirtying cache
            session = dict(session)
            session["ai_summary"] = ollama.get_cached_summary(session["session_id"])
            collected.append((session, cwd, mtime))

            # Track newest mtime per CWD for CWD-based active-session matching
            if cwd and cwd in cwd_pids and mtime > cwd_newest_mtime.get(cwd, 0):
                cwd_newest_mtime[cwd] = mtime

    # Second in-memory pass: annotate is_active/pid now that cwd_newest_mtime is complete
    sessions: list[dict] = []
    for session, cwd, mtime in collected:
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

    # Sort newest-first within each activity group (matches SQLite ORDER BY last_active DESC)
    sessions.sort(key=lambda s: constants._normalize_ts(s.get("last_active") or ""), reverse=True)
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

    now = datetime.now(UTC)
    period_cutoff = now - timedelta(hours=time_range_hours)
    def _in_period(ts: str | None) -> bool:
        if not ts:
            return False
        try:
            return datetime.fromisoformat(constants._normalize_ts(ts)) >= period_cutoff
        except ValueError:
            return False
    cost_today_val = sum(
        s["stats"]["estimated_cost_usd"]
        for s in sessions
        if _in_period(s.get("last_active"))
    )

    one_week_ago = now - timedelta(days=7)
    cost_week_usd = 0.0
    for s in sessions:
        try:
            la = s.get("last_active")
            if la and datetime.fromisoformat(constants._normalize_ts(la)) >= one_week_ago:
                cost_week_usd += s["stats"]["estimated_cost_usd"]
        except (ValueError, KeyError):
            pass

    return {
        "total_sessions": len(sessions),
        "active_sessions": active_count,
        "total_cost_usd": round(total_cost, 4),
        "cost_today_usd": round(cost_today_val, 4),
        "cost_week_usd": round(cost_week_usd, 4),
        "total_tokens": total_tokens,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_cache_create_tokens": total_cache_create,
        "total_cache_read_tokens": total_cache_read,
        "total_turns": total_turns,
        "total_subagents": total_subagents,
    }


def get_sessions_for_range(
    time_range: str,
    start: str | None = None,
    end: str | None = None,
) -> list[dict]:
    """Dispatch to JSONL (short ranges) or SQLite (historical ranges)."""
    hours = constants.TIME_RANGE_HOURS.get(time_range, 24)

    # Custom range always routes to SQLite
    if start or end:
        return database.get_sessions_from_db(start=start, end=end)

    # "all" routes to SQLite with no cutoff
    if hours is None:
        return database.get_sessions_from_db()

    # Existing routing logic unchanged
    if hours <= constants.LIVE_HOURS:
        return get_all_sessions(hours=hours)
    return database.get_sessions_from_db(hours=hours)
