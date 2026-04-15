"""Config read/write helpers for Claude Sessions UI backend."""

import json
import time
from pathlib import Path

from . import constants

_config_cache: tuple[float, dict] | None = None


def _read_config_from_disk() -> dict:
    if constants.CONFIG_PATH.exists():
        try:
            with open(constants.CONFIG_PATH) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"daily_budget_usd": None, "weekly_budget_usd": None}


def read_config() -> dict:
    global _config_cache
    now = time.monotonic()
    if _config_cache and now - _config_cache[0] < 5:
        return _config_cache[1]
    data = _read_config_from_disk()
    _config_cache = (now, data)
    return data


def write_config(data: dict) -> None:
    constants.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    constants.CONFIG_PATH.write_text(json.dumps(data, indent=2))
    global _config_cache
    _config_cache = None  # invalidate cache


def check_budget_status(stats: dict, config: dict) -> dict:
    daily_limit  = config.get("daily_budget_usd")
    weekly_limit = config.get("weekly_budget_usd")
    daily_spent  = stats.get("cost_today_usd", 0.0)
    weekly_spent = stats.get("cost_week_usd",  0.0)

    def make_entry(limit, spent):
        if limit is None:
            return None
        return {
            "limit":    limit,
            "spent":    spent,
            "exceeded": spent >= limit,
            "pct":      round(spent / limit * 100, 1) if limit > 0 else 0,
        }

    return {
        "daily":  make_entry(daily_limit, daily_spent),
        "weekly": make_entry(weekly_limit, weekly_spent),
    }


def validate_flag_path(raw: str) -> Path | None:
    if not raw:
        return None
    p = Path(raw).expanduser().resolve()
    claude_dir = (Path.home() / ".claude").resolve()
    if not p.is_relative_to(claude_dir):
        raise ValueError("budget_flag_path must be within ~/.claude/")
    return p
