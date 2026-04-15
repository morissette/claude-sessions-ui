"""Session detail helpers for Claude Sessions UI backend."""

import asyncio
import contextlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from . import constants

logger = logging.getLogger(__name__)

# ─── Caches ───────────────────────────────────────────────────────────────────

# file path → (mtime, analytics dict)
_analytics_cache: dict[str, tuple[float, dict]] = {}


# ─── Session detail helpers ──────────────────────────────────────────────────


def find_session_file(session_id: str) -> Path | None:
    """Scan ~/.claude/projects/ for {session_id}.jsonl. Returns None if not found."""
    for path in constants.CLAUDE_DIR.glob(f"*/{session_id}.jsonl"):
        return path
    return None


def parse_session_detail(path: Path, offset: int = 0, limit: int = 200) -> dict:
    """Read a JSONL file and return structured, paginated message objects."""
    session_id = path.stem
    raw_lines: list[dict] = []

    try:
        with open(path) as f:
            for raw_line in f:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    raw_lines.append(json.loads(raw_line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return {"session_id": session_id, "total_messages": 0, "offset": offset, "limit": limit, "messages": []}

    # First pass: map tool_use_id → tool_name for pairing tool_result blocks
    tool_name_map: dict[str, str] = {}
    for d in raw_lines:
        if d.get("type") == "assistant":
            for block in d.get("message", {}).get("content", []):
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_name_map[block.get("id", "")] = block.get("name", "")

    # Second pass: normalize each line into flat message objects
    all_messages: list[dict] = []
    for idx, d in enumerate(raw_lines):
        t = d.get("type", "")
        ts = d.get("timestamp")

        if t == "user":
            content = d.get("message", {}).get("content", "")
            if isinstance(content, str):
                all_messages.append({
                    "id": idx, "type": "user", "role": "user", "content": content,
                    "tool_name": None, "tool_use_id": None, "timestamp": ts, "thinking": None,
                })
            elif isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    btype = block.get("type", "")
                    if btype == "tool_result":
                        tool_use_id = block.get("tool_use_id", "")
                        result_content = block.get("content", "")
                        if isinstance(result_content, list):
                            result_content = " ".join(
                                c.get("text", "")
                                for c in result_content
                                if isinstance(c, dict) and c.get("type") == "text"
                            )
                        if isinstance(result_content, str) and len(result_content) > 500:
                            result_content = result_content[:500] + "…[truncated]"
                        all_messages.append({
                            "id": idx, "type": "tool_result", "role": "tool",
                            "content": result_content,
                            "tool_name": tool_name_map.get(tool_use_id),
                            "tool_use_id": tool_use_id, "timestamp": ts, "thinking": None,
                        })
                    elif btype == "text":
                        text = block.get("text", "")
                        if text:
                            all_messages.append({
                                "id": idx, "type": "user", "role": "user", "content": text,
                                "tool_name": None, "tool_use_id": None, "timestamp": ts, "thinking": None,
                            })

        elif t == "assistant":
            thinking_text = None
            for block in d.get("message", {}).get("content", []):
                if not isinstance(block, dict):
                    continue
                btype = block.get("type", "")
                if btype == "thinking":
                    thinking_text = block.get("thinking", "")
                elif btype == "text":
                    all_messages.append({
                        "id": idx, "type": "assistant", "role": "assistant",
                        "content": block.get("text", ""),
                        "tool_name": None, "tool_use_id": None, "timestamp": ts,
                        "thinking": thinking_text,
                    })
                    thinking_text = None
                elif btype == "tool_use":
                    input_data = block.get("input", {})
                    input_str = json.dumps(input_data, indent=2) if isinstance(input_data, dict) else str(input_data)
                    if len(input_str) > 500:
                        input_str = input_str[:500] + "\n…[truncated]"
                    all_messages.append({
                        "id": idx, "type": "tool_use", "role": "assistant",
                        "content": input_str,
                        "tool_name": block.get("name"),
                        "tool_use_id": block.get("id"), "timestamp": ts, "thinking": None,
                    })

        elif t == "summary":
            summary_text = d.get("summary", "")
            if summary_text:
                all_messages.append({
                    "id": idx, "type": "summary", "role": "system", "content": summary_text,
                    "tool_name": None, "tool_use_id": None, "timestamp": ts, "thinking": None,
                })

    total = len(all_messages)
    return {
        "session_id": session_id,
        "total_messages": total,
        "offset": offset,
        "limit": limit,
        "messages": all_messages[offset:offset + limit],
    }


async def parse_session_analytics(session_id: str) -> dict | None:
    """Parse a JSONL session file into per-turn analytics with mtime-based caching."""
    matches = list(constants.CLAUDE_DIR.glob(f"*/{session_id}.jsonl"))
    if not matches:
        return None
    jf = matches[0]

    mtime = jf.stat().st_mtime
    cache_key = str(jf)
    if cache_key in _analytics_cache and _analytics_cache[cache_key][0] == mtime:
        return _analytics_cache[cache_key][1]

    def _parse():
        from collections import Counter
        from datetime import datetime as _dt

        turns: list[dict] = []
        tool_counts: Counter = Counter()
        current_turn: dict = {}
        turn_number = 0

        def new_turn(ts: str) -> dict:
            return {
                "input": 0, "output": 0, "cache_create": 0, "cache_read": 0,
                "thinking": 0, "cost": 0.0, "start_ts": ts, "end_ts": ts,
                "tools": [],
            }

        def finalize_turn(t: dict, n: int, model: str) -> dict:
            pricing = constants.MODEL_PRICING.get(model, constants.MODEL_PRICING["default"])
            cost = (
                t["input"]          * pricing["input"]       / 1_000_000
                + t["output"]       * pricing["output"]      / 1_000_000
                + t["cache_create"] * pricing["cache_write"] / 1_000_000
                + t["cache_read"]   * pricing["cache_read"]  / 1_000_000
            )
            dur = None
            try:
                if t["start_ts"] and t["end_ts"]:
                    a = _dt.fromisoformat(t["start_ts"].replace("Z", "+00:00"))
                    b = _dt.fromisoformat(t["end_ts"].replace("Z", "+00:00"))
                    dur = (b - a).total_seconds()
            except Exception:
                pass
            return {
                "turn": n,
                "input_tokens": t["input"],
                "output_tokens": t["output"],
                "cache_create_tokens": t["cache_create"],
                "cache_read_tokens": t["cache_read"],
                "thinking_words": t["thinking"],
                "cost_usd": cost,
                "duration_s": dur,
                "ts": t["start_ts"],
            }

        model_used = "claude-sonnet-4-6"
        try:
            with open(jf, encoding="utf-8", errors="replace") as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    msg = entry.get("message", {}) or {}
                    role = msg.get("role") or entry.get("type", "")
                    ts = entry.get("timestamp", "")

                    if role == "user":
                        content = msg.get("content", "")
                        has_text = (
                            (isinstance(content, str) and content.strip()) or
                            (isinstance(content, list) and any(
                                isinstance(b, dict) and b.get("type") == "text" for b in content
                            ))
                        )
                        if has_text:
                            if current_turn and turn_number > 0:
                                turns.append(finalize_turn(current_turn, turn_number, model_used))
                            turn_number += 1
                            current_turn = new_turn(ts)

                    elif role == "assistant":
                        if not current_turn:
                            turn_number += 1
                            current_turn = new_turn(ts)
                        usage = msg.get("usage", {}) or {}
                        current_turn["input"]        += usage.get("input_tokens", 0) or 0
                        current_turn["output"]       += usage.get("output_tokens", 0) or 0
                        current_turn["cache_create"] += usage.get("cache_creation_input_tokens", 0) or 0
                        current_turn["cache_read"]   += usage.get("cache_read_input_tokens", 0) or 0
                        current_turn["end_ts"] = ts
                        m = msg.get("model", "")
                        if m:
                            model_used = m
                        for block in (msg.get("content") or []):
                            if isinstance(block, dict) and block.get("type") == "thinking":
                                think_text = block.get("thinking", "")
                                current_turn["thinking"] += len(think_text.split()) if think_text else 0

                    elif entry.get("type") in ("tool", "tool_result") or role in ("tool",):
                        tool_name = (
                            entry.get("toolName") or entry.get("tool_name") or
                            entry.get("name") or "Unknown"
                        )
                        tool_counts[tool_name] += 1
                        if current_turn:
                            current_turn["tools"].append(tool_name)

        except OSError:
            return None

        if current_turn and turn_number > 0:
            turns.append(finalize_turn(current_turn, turn_number, model_used))

        if not turns:
            return None

        # Cumulative cost
        cumulative = []
        running = 0.0
        for t in turns:
            running += t["cost_usd"]
            cumulative.append({"turn": t["turn"], "cost_usd": running})

        # Tool usage top 10
        tool_usage = [{"tool": t, "count": c} for t, c in tool_counts.most_common(10)]

        # Summary stats
        durations = [t["duration_s"] for t in turns if t["duration_s"] is not None]
        avg_dur = sum(durations) / len(durations) if durations else None
        total_output = sum(t["output_tokens"] for t in turns)
        # thinking_words is a word count (len(text.split()), not an API token count)
        total_thinking_words = sum(t["thinking_words"] for t in turns)
        thinking_word_ratio = total_thinking_words / total_output if total_output > 0 else 0.0
        peak = max(turns, key=lambda t: t["cost_usd"])

        return {
            "session_id": session_id,
            "turns": turns[:200],
            "truncated": len(turns) > 200,
            "cumulative_cost": cumulative[:200],
            "tool_usage": tool_usage,
            "summary": {
                "total_turns": len(turns),
                "avg_turn_duration_s": avg_dur,
                "thinking_word_ratio": thinking_word_ratio,
                "peak_turn": peak["turn"],
                "peak_turn_cost_usd": peak["cost_usd"],
            },
        }

    result = await asyncio.get_event_loop().run_in_executor(None, _parse)
    if result:
        _analytics_cache[cache_key] = (mtime, result)
    return result


def render_transcript(path: Path) -> str:
    """Render all messages from a session JSONL as a readable markdown transcript."""
    session_id = path.stem
    result = parse_session_detail(path, offset=0, limit=999_999)
    messages = result["messages"]
    total = result["total_messages"]
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    lines: list[str] = [
        f"# Claude Session — {session_id[:8]}",
        "",
        f"**Session ID:** `{session_id}`  ",
        f"**Exported:** {now}  ",
        f"**Messages:** {total}",
        "",
        "---",
        "",
    ]

    for msg in messages:
        ts = ""
        if msg.get("timestamp"):
            with contextlib.suppress(ValueError):
                ts = f" · {datetime.fromisoformat(msg['timestamp'].replace('Z', '+00:00')).strftime('%H:%M:%S')}"

        mtype = msg.get("type", "")

        if mtype == "user":
            lines += [f"### You{ts}", "", msg.get("content", ""), "", "---", ""]
        elif mtype == "assistant":
            if msg.get("thinking"):
                lines += [
                    f"### Claude{ts}",
                    "",
                    "<details><summary>Extended thinking</summary>",
                    "",
                    msg["thinking"],
                    "",
                    "</details>",
                    "",
                    msg.get("content", ""),
                    "",
                    "---",
                    "",
                ]
            else:
                lines += [f"### Claude{ts}", "", msg.get("content", ""), "", "---", ""]
        elif mtype == "tool_use":
            tool = msg.get("tool_name") or "unknown"
            lines += [
                f"#### Tool: {tool}{ts}",
                "",
                "```",
                msg.get("content", ""),
                "```",
                "",
            ]
        elif mtype == "tool_result":
            tool = msg.get("tool_name") or "unknown"
            lines += [
                f"#### Result: {tool}",
                "",
                "```",
                msg.get("content", ""),
                "```",
                "",
            ]
        elif mtype == "summary":
            lines += [f"> **Summary:** {msg.get('content', '')}", ""]

    return "\n".join(lines)
