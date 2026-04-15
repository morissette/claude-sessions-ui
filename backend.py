#!/usr/bin/env python3
"""Claude Sessions UI — FastAPI backend."""

import asyncio
import contextlib
import json
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psutil
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Gauge,
    generate_latest,
)

# ─── Prometheus metrics ───────────────────────────────────────────────────────

sessions_total = Gauge("claude_sessions_total", "Total Claude sessions scanned")
sessions_active = Gauge("claude_sessions_active", "Currently active Claude sessions")
tokens_input = Gauge("claude_tokens_input_total", "Total input tokens across all sessions")
tokens_output = Gauge("claude_tokens_output_total", "Total output tokens across all sessions")
tokens_cache_create = Gauge("claude_tokens_cache_create_total", "Total cache-creation tokens")
tokens_cache_read = Gauge("claude_tokens_cache_read_total", "Total cache-read tokens")
cost_total = Gauge("claude_cost_usd_total", "Estimated total cost USD across all sessions")
cost_today = Gauge("claude_cost_usd_today", "Estimated cost USD for today")
turns_total = Gauge("claude_turns_total", "Total conversation turns across all sessions")
subagents_total = Gauge("claude_subagents_total", "Total subagents spawned across all sessions")

# ─── App setup ────────────────────────────────────────────────────────────────


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    asyncio.create_task(_startup_backfill())
    yield


app = FastAPI(title="Claude Sessions UI", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

CLAUDE_DIR = Path.home() / ".claude" / "projects"
DB_PATH = Path.home() / ".claude" / "claude-sessions-ui.db"
LIVE_HOURS = 24  # Use JSONL for this window; SQLite for everything older

TIME_RANGE_HOURS: dict[str, int] = {
    "1h": 1,
    "1d": 24,
    "3d": 72,
    "1w": 168,
    "2w": 336,
    "1m": 720,
    "6m": 4320,
}

SUMMARIES_DIR = Path.home() / ".claude" / "session_summaries"
SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)

SAVINGS_FILE = Path.home() / ".claude" / "pr_poller" / "ollama_savings.jsonl"
TRUNCATION_SAVINGS_FILE = Path.home() / ".claude" / "truncation_savings.jsonl"

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
SUMMARY_MODEL = "llama3.2:3b"

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

# ─── Caches ───────────────────────────────────────────────────────────────────

# file path → (mtime, parsed session dict)
_session_cache: dict[str, tuple[float, dict]] = {}

# file path → (mtime, cwd string)  — quick first-pass scan
_cwd_cache: dict[str, tuple[float, str]] = {}

# SQLite connection and lock
_db_conn: sqlite3.Connection | None = None
_db_lock = threading.Lock()


# ─── SQLite storage ──────────────────────────────────────────────────────────


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


def init_db() -> None:
    """Create the SQLite DB, table, and indexes. Must be called once at startup."""
    global _db_conn
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if _db_conn is not None:
        _db_conn.close()
    _db_conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    _db_conn.execute("PRAGMA journal_mode=WAL")
    _db_conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id            TEXT PRIMARY KEY,
            project_path          TEXT NOT NULL,
            project_name          TEXT NOT NULL,
            git_branch            TEXT,
            title                 TEXT NOT NULL,
            model                 TEXT NOT NULL,
            turns                 INTEGER NOT NULL DEFAULT 0,
            subagent_count        INTEGER NOT NULL DEFAULT 0,
            subagents_json        TEXT NOT NULL DEFAULT '[]',
            started_at            TEXT NOT NULL,
            last_active           TEXT NOT NULL,
            input_tokens          INTEGER NOT NULL DEFAULT 0,
            output_tokens         INTEGER NOT NULL DEFAULT 0,
            cache_create_tokens   INTEGER NOT NULL DEFAULT 0,
            cache_read_tokens     INTEGER NOT NULL DEFAULT 0,
            total_tokens          INTEGER NOT NULL DEFAULT 0,
            estimated_cost_usd    REAL NOT NULL DEFAULT 0.0,
            compact_potential_usd REAL NOT NULL DEFAULT 0.0,
            last_synced_at        TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sessions_last_active ON sessions(last_active);
        CREATE INDEX IF NOT EXISTS idx_sessions_started_at  ON sessions(started_at);
    """)
    _db_conn.commit()


def upsert_sessions_to_db(sessions: list[dict]) -> None:
    """Upsert a list of session dicts into the SQLite DB."""
    if not sessions or _db_conn is None:
        return
    now_iso = datetime.now(UTC).isoformat()
    rows = [
        (
            s["session_id"],
            s["project_path"],
            s["project_name"],
            s.get("git_branch"),
            s["title"],
            s["model"],
            s["turns"],
            s["subagent_count"],
            json.dumps(s.get("subagents", [])),
            _normalize_ts(s["started_at"]),
            _normalize_ts(s["last_active"]),
            s["stats"]["input_tokens"],
            s["stats"]["output_tokens"],
            s["stats"]["cache_create_tokens"],
            s["stats"]["cache_read_tokens"],
            s["stats"]["total_tokens"],
            s["stats"]["estimated_cost_usd"],
            s.get("compact_potential_usd", 0.0),
            now_iso,
        )
        for s in sessions
    ]
    with _db_lock:
        _db_conn.executemany(
            """
            INSERT INTO sessions (
                session_id, project_path, project_name, git_branch, title, model,
                turns, subagent_count, subagents_json, started_at, last_active,
                input_tokens, output_tokens, cache_create_tokens, cache_read_tokens,
                total_tokens, estimated_cost_usd, compact_potential_usd, last_synced_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(session_id) DO UPDATE SET
                project_path=excluded.project_path,
                project_name=excluded.project_name,
                git_branch=excluded.git_branch,
                title=excluded.title,
                model=excluded.model,
                turns=excluded.turns,
                subagent_count=excluded.subagent_count,
                subagents_json=excluded.subagents_json,
                last_active=excluded.last_active,
                input_tokens=excluded.input_tokens,
                output_tokens=excluded.output_tokens,
                cache_create_tokens=excluded.cache_create_tokens,
                cache_read_tokens=excluded.cache_read_tokens,
                total_tokens=excluded.total_tokens,
                estimated_cost_usd=excluded.estimated_cost_usd,
                compact_potential_usd=excluded.compact_potential_usd,
                last_synced_at=excluded.last_synced_at
            """,
            rows,
        )
        _db_conn.commit()


def get_sessions_from_db(hours: int) -> list[dict]:
    """Return sessions from SQLite for time ranges beyond LIVE_HOURS."""
    if _db_conn is None:
        return []
    cutoff = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
    processes = get_running_claude_processes()
    session_pid: dict[str, int] = {
        info["session_id"]: pid
        for pid, info in processes.items()
        if info["session_id"]
    }
    with _db_lock:
        cur = _db_conn.execute(
            "SELECT * FROM sessions WHERE last_active >= ? ORDER BY last_active DESC",
            (cutoff,),
        )
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    sessions = []
    for row in rows:
        s: dict = {
            "session_id": row["session_id"],
            "project_path": row["project_path"],
            "project_name": row["project_name"],
            "git_branch": row["git_branch"],
            "title": row["title"],
            "model": row["model"],
            "turns": row["turns"],
            "subagent_count": row["subagent_count"],
            "subagents": json.loads(row["subagents_json"]),
            "started_at": row["started_at"],
            "last_active": row["last_active"],
            "last_activity": None,
            "stats": {
                "input_tokens": row["input_tokens"],
                "output_tokens": row["output_tokens"],
                "cache_create_tokens": row["cache_create_tokens"],
                "cache_read_tokens": row["cache_read_tokens"],
                "total_tokens": row["total_tokens"],
                "estimated_cost_usd": row["estimated_cost_usd"],
            },
            "compact_potential_usd": row["compact_potential_usd"],
            "is_active": False,
            "pid": None,
            "ai_summary": get_cached_summary(row["session_id"]),
        }
        if row["session_id"] in session_pid:
            s["is_active"] = True
            s["pid"] = session_pid[row["session_id"]]
        sessions.append(s)

    sessions.sort(key=lambda s: not s["is_active"])
    return sessions


def get_sessions_for_range(time_range: str) -> list[dict]:
    """Dispatch to JSONL (short ranges) or SQLite (historical ranges)."""
    hours = TIME_RANGE_HOURS.get(time_range, 24)
    if hours <= LIVE_HOURS:
        return get_all_sessions(hours=hours)
    return get_sessions_from_db(hours=hours)


def get_all_sessions_unbounded() -> list[dict]:
    """Parse all JSONL sessions regardless of age — used for startup DB backfill."""
    return get_all_sessions(hours=None)


async def _startup_backfill() -> None:
    """Asynchronously backfill all historical JSONL sessions into SQLite."""
    loop = asyncio.get_event_loop()
    sessions = await loop.run_in_executor(None, get_all_sessions_unbounded)
    await loop.run_in_executor(None, upsert_sessions_to_db, sessions)


# ─── Process discovery ────────────────────────────────────────────────────────

def get_running_claude_processes() -> dict[int, dict]:
    """Return {pid: {cwd, session_id, create_time}} for all claude processes."""
    result: dict[int, dict] = {}
    for p in psutil.process_iter(["pid", "name", "cmdline", "cwd", "create_time"]):
        try:
            name = p.info["name"] or ""
            cmdline = p.info["cmdline"] or []
            is_claude = name == "claude" or any(
                c.endswith("/claude") or c.endswith("/claude-code") or c == "claude"
                for c in cmdline[:2] if c
            )
            if not is_claude:
                continue
            session_id = None
            for i, arg in enumerate(cmdline):
                if arg == "--resume" and i + 1 < len(cmdline):
                    session_id = cmdline[i + 1]
                    break
            result[p.info["pid"]] = {
                "pid": p.info["pid"],
                "cwd": p.info["cwd"],
                "session_id": session_id,
                "create_time": p.info["create_time"],
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return result


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
        with open(jsonl_path) as f:
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
        with open(jsonl_path) as f:
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
        stat = jsonl_path.stat()
        first_timestamp = datetime.fromtimestamp(
            stat.st_ctime, tz=UTC
        ).isoformat()

    pricing = MODEL_PRICING.get(model or "", MODEL_PRICING["default"])
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


# ─── Session aggregation ─────────────────────────────────────────────────────

def get_all_sessions(hours: int | None = 24) -> list[dict]:
    if not CLAUDE_DIR.exists():
        return []

    processes = get_running_claude_processes()
    cwd_pids: dict[str, list[int]] = {}
    session_pid: dict[str, int] = {}

    for pid, info in processes.items():
        if info["cwd"]:
            cwd_pids.setdefault(info["cwd"], []).append(pid)
        if info["session_id"]:
            session_pid[info["session_id"]] = pid

    now = time.time()
    cutoff = (now - hours * 3600) if hours is not None else 0
    sessions: list[dict] = []

    # For CWD-based matching (no --resume), only the NEWEST session in each
    # project dir should be considered active.  Pre-compute: cwd → newest mtime.
    cwd_newest_mtime: dict[str, float] = {}

    for project_dir in CLAUDE_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        for jsonl_file in project_dir.glob("*.jsonl"):
            try:
                mtime = jsonl_file.stat().st_mtime
            except OSError:
                continue
            if mtime < cutoff:
                continue
            cwd = get_session_cwd(jsonl_file)
            if cwd and cwd in cwd_pids and mtime > cwd_newest_mtime.get(cwd, 0):
                cwd_newest_mtime[cwd] = mtime

    for project_dir in CLAUDE_DIR.iterdir():
        if not project_dir.is_dir():
            continue

        for jsonl_file in project_dir.glob("*.jsonl"):
            try:
                mtime = jsonl_file.stat().st_mtime
            except OSError:
                continue
            if mtime < cutoff:
                continue

            cwd = get_session_cwd(jsonl_file)
            project_path = cwd or ("/" + project_dir.name.lstrip("-"))

            session = parse_session_file(jsonl_file, project_path)
            if session is None:
                continue

            # Shallow copy so we can annotate is_active/pid/summary without dirtying cache
            session = dict(session)
            session["ai_summary"] = get_cached_summary(session["session_id"])

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

    sessions.sort(key=lambda s: (not s["is_active"], s.get("last_active") or ""), reverse=False)
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

    period_cutoff = datetime.now(UTC) - timedelta(hours=time_range_hours)
    def _in_period(ts: str | None) -> bool:
        if not ts:
            return False
        try:
            return datetime.fromisoformat(_normalize_ts(ts)) >= period_cutoff
        except ValueError:
            return False
    cost_today_val = sum(
        s["stats"]["estimated_cost_usd"]
        for s in sessions
        if _in_period(s.get("last_active"))
    )

    return {
        "total_sessions": len(sessions),
        "active_sessions": active_count,
        "total_cost_usd": round(total_cost, 4),
        "cost_today_usd": round(cost_today_val, 4),
        "total_tokens": total_tokens,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_cache_create_tokens": total_cache_create,
        "total_cache_read_tokens": total_cache_read,
        "total_turns": total_turns,
        "total_subagents": total_subagents,
    }


def _update_prometheus(stats: dict) -> None:
    sessions_total.set(stats["total_sessions"])
    sessions_active.set(stats["active_sessions"])
    tokens_input.set(stats["total_input_tokens"])
    tokens_output.set(stats["total_output_tokens"])
    tokens_cache_create.set(stats["total_cache_create_tokens"])
    tokens_cache_read.set(stats["total_cache_read_tokens"])
    cost_total.set(stats["total_cost_usd"])
    cost_today.set(stats["cost_today_usd"])
    turns_total.set(stats["total_turns"])
    subagents_total.set(stats["total_subagents"])


# ─── Ollama helpers ──────────────────────────────────────────────────────────

def ollama_is_available() -> bool:
    try:
        req = urllib.request.Request(f"{OLLAMA_URL}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3):
            return True
    except Exception:
        return False


def ollama_model_pulled(model: str) -> bool:
    try:
        req = urllib.request.Request(f"{OLLAMA_URL}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
        names = [m["name"] for m in data.get("models", [])]
        base = model.split(":")[0]
        return any(base in n for n in names)
    except Exception:
        return False


def ollama_summarize(text: str, model: str = SUMMARY_MODEL) -> str | None:
    """Call local Ollama to produce a short task title from a raw user message."""
    prompt = (
        "Summarize this task request in 6-10 words. "
        "Start with a verb. No punctuation at the end. Be specific.\n\n"
        + text[:600]
    )
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode()
    try:
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read()).get("response", "").strip()
            # Strip surrounding quotes if model added them
            return result.strip('"').strip("'")
    except Exception:
        return None


def get_cached_summary(session_id: str) -> str | None:
    p = SUMMARIES_DIR / f"{session_id}.txt"
    try:
        return p.read_text().strip() or None
    except OSError:
        return None


def cache_summary(session_id: str, summary: str) -> None:
    (SUMMARIES_DIR / f"{session_id}.txt").write_text(summary)


def compute_truncation_savings() -> dict:
    """Read truncation hook log and aggregate savings per tool."""
    by_tool: dict[str, dict] = {}
    if not TRUNCATION_SAVINGS_FILE.exists():
        return {"tools": {}, "total_tokens_saved": 0, "total_cost_saved_usd": 0.0}
    try:
        for line in TRUNCATION_SAVINGS_FILE.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            tool = e.get("tool", "Unknown")
            if tool not in by_tool:
                by_tool[tool] = {"count": 0, "tokens_saved": 0, "cost_saved_usd": 0.0}
            by_tool[tool]["count"] += 1
            by_tool[tool]["tokens_saved"] += e.get("tokens_saved", 0)
            by_tool[tool]["cost_saved_usd"] = round(
                by_tool[tool]["cost_saved_usd"] + e.get("cost_saved_usd", 0.0), 6
            )
    except OSError:
        pass

    total_tokens = sum(v["tokens_saved"] for v in by_tool.values())
    total_cost = round(sum(v["cost_saved_usd"] for v in by_tool.values()), 4)
    return {
        "tools": by_tool,
        "total_tokens_saved": total_tokens,
        "total_cost_saved_usd": total_cost,
    }


def compute_ollama_savings() -> dict:
    """Read pr_poller savings log + summary cache to compute total saved cost."""
    pr_skips: list[dict] = []
    if SAVINGS_FILE.exists():
        try:
            for line in SAVINGS_FILE.read_text().splitlines():
                line = line.strip()
                if line:
                    with contextlib.suppress(json.JSONDecodeError):
                        pr_skips.append(json.loads(line))
        except OSError:
            pass

    summary_count = len(list(SUMMARIES_DIR.glob("*.txt")))

    pr_skip_count = len(pr_skips)
    pr_saved_usd = sum(float(e.get("saved_usd", 0)) for e in pr_skips)
    summary_saved_usd = summary_count * SUMMARY_COST_ESTIMATE_USD
    total_saved_usd = pr_saved_usd + summary_saved_usd

    return {
        "pr_skips": pr_skip_count,
        "pr_saved_usd": round(pr_saved_usd, 4),
        "summaries_generated": summary_count,
        "summary_saved_usd": round(summary_saved_usd, 6),
        "total_saved_usd": round(total_saved_usd, 4),
        "recent_skips": [
            {"ts": e.get("ts"), "title": e.get("title", ""), "url": e.get("url", "")}
            for e in pr_skips[-5:]  # last 5 for the UI
        ],
    }


# ─── HTTP endpoints ──────────────────────────────────────────────────────────

@app.get("/api/sessions")
async def list_sessions(time_range: str = "1d"):
    if time_range not in TIME_RANGE_HOURS:
        time_range = "1d"
    hours = TIME_RANGE_HOURS[time_range]
    sess = get_sessions_for_range(time_range)
    stats = compute_global_stats(sess, hours)
    _update_prometheus(stats)
    # Only upsert when sessions came from JSONL (live path); historical DB reads
    # don't need to be written back and would add unnecessary write contention.
    if hours <= LIVE_HOURS:
        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, upsert_sessions_to_db, sess)
    return {
        "sessions": sess,
        "stats": stats,
        "savings": compute_ollama_savings(),
        "truncation": compute_truncation_savings(),
        "time_range": time_range,
    }


@app.get("/api/db/status")
async def db_status():
    if _db_conn is None:
        return {"total_stored": 0, "oldest": None, "newest": None, "db_path": str(DB_PATH)}
    with _db_lock:
        cur = _db_conn.execute("SELECT COUNT(*), MIN(last_active), MAX(last_active) FROM sessions")
        count, oldest, newest = cur.fetchone()
    return {"total_stored": count, "oldest": oldest, "newest": newest, "db_path": str(DB_PATH)}


@app.get("/api/ollama")
async def ollama_status():
    available = ollama_is_available()
    model_ready = ollama_model_pulled(SUMMARY_MODEL) if available else False
    return {
        "available": available,
        "model": SUMMARY_MODEL,
        "model_ready": model_ready,
        "url": OLLAMA_URL,
    }


@app.post("/api/sessions/{session_id}/summarize")
async def summarize_session(session_id: str):
    # Return cached summary if we have it
    cached = get_cached_summary(session_id)
    if cached:
        return {"session_id": session_id, "summary": cached, "cached": True}

    # Find the session to get its title text
    sessions = get_all_sessions()
    session = next((s for s in sessions if s["session_id"] == session_id), None)
    if session is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Session not found")

    raw_title = session.get("title", "")
    if not raw_title:
        return {"session_id": session_id, "summary": None, "cached": False}

    # Run Ollama in a thread so we don't block the event loop
    loop = asyncio.get_event_loop()
    summary = await loop.run_in_executor(None, ollama_summarize, raw_title)

    if summary:
        cache_summary(session_id, summary)
    return {"session_id": session_id, "summary": summary, "cached": False}


@app.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics():
    # Trigger a refresh so metrics are fresh
    sess = get_all_sessions()
    stats = compute_global_stats(sess, LIVE_HOURS)
    _update_prometheus(stats)
    return PlainTextResponse(
        generate_latest().decode("utf-8"), media_type=CONTENT_TYPE_LATEST
    )


# ─── WebSocket ────────────────────────────────────────────────────────────────

_active_ws: list[WebSocket] = []


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, time_range: str = "1d"):
    if time_range not in TIME_RANGE_HOURS:
        time_range = "1d"
    await ws.accept()
    _active_ws.append(ws)
    try:
        while True:
            sess = get_sessions_for_range(time_range)
            hours = TIME_RANGE_HOURS[time_range]
            stats = compute_global_stats(sess, hours)
            _update_prometheus(stats)
            # Only upsert for live JSONL ranges; skip DB-sourced reads to avoid write churn.
            if hours <= LIVE_HOURS:
                asyncio.get_event_loop().run_in_executor(None, upsert_sessions_to_db, sess)
            await ws.send_json({
                "sessions": sess,
                "stats": stats,
                "savings": compute_ollama_savings(),
                "truncation": compute_truncation_savings(),
                "time_range": time_range,
            })
            # Historical ranges can poll slower — no live JSONL to watch
            interval = 2 if TIME_RANGE_HOURS.get(time_range, 24) <= LIVE_HOURS else 10
            await asyncio.sleep(interval)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if ws in _active_ws:
            _active_ws.remove(ws)


# ─── Serve built frontend ────────────────────────────────────────────────────

_frontend_dist = Path(__file__).parent / "frontend" / "dist"
if _frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="static")


if __name__ == "__main__":

    import uvicorn

    LOG_FILE = str(Path.home() / ".claude" / "claude-sessions-ui.log")
    log_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "()": "uvicorn.logging.DefaultFormatter",
                "fmt": "%(asctime)s %(levelprefix)s %(message)s",
            }
        },
        "handlers": {
            "file": {
                "class": "logging.FileHandler",
                "filename": LOG_FILE,
                "formatter": "default",
            }
        },
        "loggers": {
            "uvicorn": {"handlers": ["file"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"handlers": ["file"], "level": "INFO", "propagate": False},
            "uvicorn.access": {"handlers": ["file"], "level": "INFO", "propagate": False},
        },
    }
    uvicorn.run(app, host="0.0.0.0", port=8765, reload=False, log_config=log_config)
