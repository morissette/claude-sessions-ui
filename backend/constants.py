"""Module-level constants for Claude Sessions UI backend."""

import os
from datetime import UTC, datetime
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude" / "projects"
DB_PATH = Path.home() / ".claude" / "claude-sessions-ui.db"
LIVE_HOURS = 24  # Use JSONL for this window; SQLite for everything older

TIME_RANGE_HOURS: dict[str, int | None] = {
    "1h":  1,
    "1d":  24,
    "3d":  72,
    "1w":  168,
    "2w":  336,
    "1m":  720,
    "6m":  4320,
    "all": None,   # None = no cutoff
}

SUMMARIES_DIR = Path.home() / ".claude" / "session_summaries"

SKILLS_DIR = Path.home() / ".claude" / "skills"

SAVINGS_FILE = Path.home() / ".claude" / "pr_poller" / "ollama_savings.jsonl"
TRUNCATION_SAVINGS_FILE = Path.home() / ".claude" / "truncation_savings.jsonl"

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
SUMMARY_MODEL = "llama3.2:3b"

CONFIG_PATH = Path.home() / ".claude" / "claude-sessions-ui-config.json"

CLAUDE_BASE_DIR = Path.home() / ".claude"

MEMORY_ALLOWLIST = [
    "memory",
    "projects",
    "commands",
    "agents",
    "skills",
    "hooks",
    "todos",
]
MEMORY_ALLOWLIST_FILES = [
    "settings.json",
    "settings.local.json",
    "CLAUDE.md",
]

# Cost we'd pay for one summary via Claude Haiku (~500 input + ~15 output tokens)
SUMMARY_COST_ESTIMATE_USD = round(500 * 0.8 / 1_000_000 + 15 * 4.0 / 1_000_000, 6)  # ~$0.00046

MODEL_PRICING: dict[str, dict[str, float]] = {
    # Prices per million tokens
    "claude-opus-4-6":              {"input": 15.00, "output": 75.00, "cache_write":  18.75, "cache_read": 1.50},
    "claude-sonnet-4-6":            {"input":  3.00, "output": 15.00, "cache_write":   3.75, "cache_read": 0.30},
    "claude-sonnet-4-5":            {"input":  3.00, "output": 15.00, "cache_write":   3.75, "cache_read": 0.30},
    "claude-haiku-4-5":             {"input":  0.80, "output":  4.00, "cache_write":   1.00, "cache_read": 0.08},
    "claude-haiku-4-5-20251001":    {"input":  0.80, "output":  4.00, "cache_write":   1.00, "cache_read": 0.08},
    "claude-3-5-sonnet-20241022":   {"input":  3.00, "output": 15.00, "cache_write":   3.75, "cache_read": 0.30},
    "claude-3-5-haiku-20241022":    {"input":  0.80, "output":  4.00, "cache_write":   1.00, "cache_read": 0.08},
    "claude-3-opus-20240229":       {"input": 15.00, "output": 75.00, "cache_write":  18.75, "cache_read": 1.50},
    "default":                      {"input":  3.00, "output": 15.00, "cache_write":   3.75, "cache_read": 0.30},
}


def _normalize_ts(ts: str) -> str:
    """Normalize an ISO 8601 timestamp to consistent +00:00 UTC format for SQLite sorting.

    JSONL files use the 'Z' suffix; Python isoformat() uses '+00:00'. Storing a
    mix causes lexicographic range queries to mis-sort because 'Z' (0x5A) sorts
    after '+' (0x2B) in ASCII. This converts both forms to the +00:00 variant.
    """
    if not ts:
        return ts
    try:
        normalized = ts[:-1] + "+00:00" if ts.endswith("Z") else ts
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.isoformat()
    except (ValueError, AttributeError):
        return ts
