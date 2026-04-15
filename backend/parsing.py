"""Session parsing helpers for Claude Sessions UI backend."""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from . import constants

logger = logging.getLogger(__name__)

# ─── Caches ───────────────────────────────────────────────────────────────────

# file path → (mtime, parsed session dict)
_session_cache: dict[str, tuple[float, dict]] = {}

# file path → (mtime, cwd string)  — quick first-pass scan
_cwd_cache: dict[str, tuple[float, str]] = {}


# ─── Session parsing ──────────────────────────────────────────────────────────

def get_session_cwd(jsonl_path: Path) -> str | None:
    """Quick scan for cwd in the first 25 lines."""
    key = str(jsonl_path)
    try:
        mtime = jsonl_path.stat().st_mtime
    except OSError:
        return None
    if key in _cwd_cache and _cwd_cache[key][0] == mtime:
        return _cwd_cache[key][1]
    try:
        with open(jsonl_path, encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i > 25:
                    break
                try:
                    d = json.loads(line)
                    if d.get("cwd"):
                        _cwd_cache[key] = (mtime, d["cwd"])
                        return d["cwd"]
                except (json.JSONDecodeError, KeyError):
                    pass
    except OSError:
        pass
    return None


def parse_session_file(jsonl_path: Path, project_path: str) -> dict | None:
    """Parse a JSONL session file into a session dict (with mtime-based cache)."""
    key = str(jsonl_path)
    try:
        mtime = jsonl_path.stat().st_mtime
    except OSError:
        return None

    if key in _session_cache and _session_cache[key][0] == mtime:
        return _session_cache[key][1]

    usage = {"input": 0, "output": 0, "cache_create": 0, "cache_read": 0}
    model: str | None = None
    git_branch: str | None = None
    first_user_text: str | None = None
    last_tool_name: str | None = None
    last_assistant_snippet: str | None = None
    turns = 0
    first_timestamp: str | None = None
    last_timestamp: str | None = None

    try:
        with open(jsonl_path, encoding="utf-8", errors="replace") as f:
            for raw_line in f:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    d = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue

                t = d.get("type")
                ts = d.get("timestamp")
                if ts:
                    if first_timestamp is None:
                        first_timestamp = ts
                    last_timestamp = ts

                if not git_branch and d.get("gitBranch"):
                    git_branch = d["gitBranch"]

                if t == "user":
                    msg = d.get("message", {})
                    content = msg.get("content", "")
                    text = ""
                    if isinstance(content, str):
                        text = content
                    elif isinstance(content, list):
                        for c in content:
                            if isinstance(c, dict) and c.get("type") == "text":
                                text = c.get("text", "")
                                break
                    if text and not isinstance(msg.get("content"), list):
                        # plain text user message (not tool results)
                        if first_user_text is None:
                            first_user_text = text
                        turns += 1
                    elif text:
                        # could be tool result list — check for actual human input
                        has_tool_result = any(
                            isinstance(c, dict) and c.get("type") == "tool_result"
                            for c in (content if isinstance(content, list) else [])
                        )
                        if not has_tool_result:
                            if first_user_text is None:
                                first_user_text = text
                            turns += 1

                elif t == "assistant":
                    msg = d.get("message", {})
                    if not model:
                        model = msg.get("model")
                    u = msg.get("usage", {})
                    usage["input"] += u.get("input_tokens", 0)
                    usage["output"] += u.get("output_tokens", 0)
                    usage["cache_create"] += u.get("cache_creation_input_tokens", 0)
                    usage["cache_read"] += u.get("cache_read_input_tokens", 0)
                    content = msg.get("content", [])
                    if isinstance(content, list):
                        for c in content:
                            if isinstance(c, dict):
                                if c.get("type") == "text" and c.get("text"):
                                    last_assistant_snippet = c["text"][:120]
                                elif c.get("type") == "tool_use":
                                    last_tool_name = c.get("name")

    except OSError:
        return None

    if not first_timestamp:
        # Reuse the mtime already fetched above — st_ctime on Linux is
        # change-time (not creation time) and can be misleading.
        first_timestamp = datetime.fromtimestamp(mtime, tz=UTC).isoformat()

    pricing = constants.MODEL_PRICING.get(model or "", constants.MODEL_PRICING["default"])
    cost = (
        usage["input"]        * pricing["input"]        / 1_000_000
        + usage["output"]       * pricing["output"]       / 1_000_000
        + usage["cache_create"] * pricing["cache_write"]  / 1_000_000
        + usage["cache_read"]   * pricing["cache_read"]   / 1_000_000
    )

    session_id = jsonl_path.stem
    subagents_dir = jsonl_path.parent / session_id / "subagents"
    subagents = []
    if subagents_dir.exists():
        for meta_file in subagents_dir.glob("*.meta.json"):
            try:
                with open(meta_file) as f:
                    meta = json.load(f)
                agent_id = meta_file.name.replace(".meta.json", "")
                subagents.append(
                    {"id": agent_id, "agent_type": meta.get("agentType", "general-purpose")}
                )
            except (OSError, json.JSONDecodeError):
                pass

    # Estimate potential savings from running /compact:
    # If turns > 10, each new turn repeats ~cache_read_tokens worth of context.
    # Compaction reduces that by ~50%.  Show savings over the next 10 hypothetical turns.
    compact_potential_usd = 0.0
    if turns > 10 and usage["cache_read"] > 0:
        per_turn_cache_cost = usage["cache_read"] / turns * pricing["cache_read"] / 1_000_000
        compact_potential_usd = round(per_turn_cache_cost * 10 * 0.5, 6)

    data: dict = {
        "session_id": session_id,
        "project_path": project_path,
        "project_name": Path(project_path).name,
        "git_branch": git_branch,
        "title": (first_user_text or "Untitled session")[:150],
        "last_activity": last_tool_name or (last_assistant_snippet or None),
        "model": model or "unknown",
        "turns": turns,
        "subagents": subagents,
        "subagent_count": len(subagents),
        "started_at": first_timestamp,
        "last_active": last_timestamp or first_timestamp,
        "stats": {
            "input_tokens": usage["input"],
            "output_tokens": usage["output"],
            "cache_create_tokens": usage["cache_create"],
            "cache_read_tokens": usage["cache_read"],
            "total_tokens": sum(usage.values()),
            "estimated_cost_usd": round(cost, 6),
        },
        "compact_potential_usd": compact_potential_usd,
        "is_active": False,
        "pid": None,
    }

    _session_cache[key] = (mtime, data)
    return data
