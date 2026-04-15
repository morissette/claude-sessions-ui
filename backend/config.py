"""Config read/write helpers for Claude Sessions UI backend."""

import json
import time

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
