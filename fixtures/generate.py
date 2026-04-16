"""Fixture data generator for Claude Sessions UI.

Generates realistic JSONL session files under ``output_dir/projects/``.
All timestamps are relative to "now" so sessions always appear in the 1h
and 1d UI time-range views regardless of when the generator is run.

CLI usage::

    python fixtures/generate.py --output-dir /tmp/claude-demo

Module usage::

    from fixtures.generate import generate
    projects_root = generate("/tmp/claude-demo")
"""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path


# ─── Helpers ────────────────────────────────────────────────────────────────


def _ts(minutes_ago: int) -> str:
    """ISO 8601 UTC timestamp N minutes before now."""
    return (datetime.now(UTC) - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _uid() -> str:
    """Random UUID string."""
    return str(uuid.uuid4())


def _user(content: str, *, ts: str, cwd: str, branch: str | None = None) -> dict:
    """Plain-text user message (counts as a turn in session stats)."""
    record: dict = {
        "type": "user",
        "timestamp": ts,
        "cwd": cwd,
        "message": {"role": "user", "content": content},
    }
    if branch:
        record["gitBranch"] = branch
    return record


def _tool_result(tool_use_id: str, output: str, *, ts: str) -> dict:
    """User tool-result message (does NOT count as a turn)."""
    return {
        "type": "user",
        "timestamp": ts,
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": output}],
        },
    }


def _assistant(
    model: str,
    text: str,
    *,
    ts: str,
    input_tokens: int,
    output_tokens: int,
    cache_create: int = 0,
    cache_read: int = 0,
    tool_name: str | None = None,
    tool_id: str | None = None,
    tool_input: dict | None = None,
    thinking: str | None = None,
) -> dict:
    """Assistant message, optionally with a thinking block and/or tool-use block."""
    content: list[dict] = []
    if thinking:
        content.append({"type": "thinking", "thinking": thinking})
    if text:
        content.append({"type": "text", "text": text})
    if tool_name and tool_id:
        content.append(
            {"type": "tool_use", "id": tool_id, "name": tool_name, "input": tool_input or {}}
        )
    return {
        "type": "assistant",
        "timestamp": ts,
        "message": {
            "role": "assistant",
            "model": model,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_creation_input_tokens": cache_create,
                "cache_read_input_tokens": cache_read,
            },
            "content": content,
        },
    }


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


# ─── Session definitions ─────────────────────────────────────────────────────
#
# All sessions use timestamps relative to now so they always appear in the
# 1h and 1d UI views. Layout:
#
#   Session A — myproject     — claude-sonnet-4-6 — 15 min ago — tool use
#   Session B — myproject     — claude-opus-4-6   — 25 min ago — thinking blocks
#   Session C — api-service   — claude-haiku-4-5  —  8 min ago — short/cheap
#   Session D — api-service   — claude-sonnet-4-6 — 50 min ago — multi-turn debug
#   Session E — data-pipeline — claude-sonnet-4-6 — 35 min ago — subagent metadata
#   Session F — data-pipeline — claude-haiku-4-5  — 45 min ago — summary block


def _session_a(projects_root: Path) -> None:
    """myproject — claude-sonnet-4-6 — tool use (Bash, Write, Edit) — 6 turns."""
    sid = _uid()
    cwd = "/home/user/myproject"
    model = "claude-sonnet-4-6"
    base = 15  # last message this many minutes ago

    tu1, tu2, tu3, tu4 = _uid(), _uid(), _uid(), _uid()

    records = [
        _user(
            "Refactor the authentication middleware to use JWT tokens",
            ts=_ts(base + 10), cwd=cwd, branch="main",
        ),
        _assistant(
            model,
            "I'll refactor the auth middleware to use JWT. Let me start by reviewing the current"
            " implementation.",
            ts=_ts(base + 9), input_tokens=800, output_tokens=320, cache_create=2400,
            tool_name="Bash", tool_id=tu1, tool_input={"command": "cat backend/auth.py"},
        ),
        _tool_result(
            tu1,
            "# auth.py\ndef authenticate(token):\n    # basic token check\n"
            "    return token == SECRET_KEY",
            ts=_ts(base + 8),
        ),
        _assistant(
            model,
            "The current implementation does a plain equality check. I'll rewrite it to use"
            " PyJWT with proper expiry and signature validation.",
            ts=_ts(base + 8), input_tokens=1200, output_tokens=480, cache_read=2400,
            tool_name="Write", tool_id=tu2,
            tool_input={"file_path": "backend/auth.py", "content": "import jwt\n# ..."},
        ),
        _tool_result(tu2, "File written successfully.", ts=_ts(base + 7)),
        _assistant(
            model,
            "JWT implementation written. Running the tests to verify.",
            ts=_ts(base + 7), input_tokens=1600, output_tokens=200, cache_read=4000,
            tool_name="Bash", tool_id=tu3,
            tool_input={"command": "pytest tests/test_auth.py -v"},
        ),
        _tool_result(
            tu3,
            "tests/test_auth.py::test_valid_token PASSED\n"
            "tests/test_auth.py::test_invalid_token PASSED\n2 passed in 0.4s",
            ts=_ts(base + 6),
        ),
        _assistant(
            model,
            "All auth tests pass. The JWT middleware is working correctly.",
            ts=_ts(base + 6), input_tokens=1800, output_tokens=150, cache_read=5500,
        ),
        _user("Add error handling for expired tokens", ts=_ts(base + 5), cwd=cwd),
        _assistant(
            model,
            "Adding ExpiredSignatureError handling with a clear 401 response.",
            ts=_ts(base + 4), input_tokens=2000, output_tokens=380, cache_read=6000,
            tool_name="Edit", tool_id=tu4,
            tool_input={
                "file_path": "backend/auth.py",
                "old_string": "jwt.decode(token, SECRET_KEY)",
                "new_string": "jwt.decode(token, SECRET_KEY, options={'verify_exp': True})",
            },
        ),
        _tool_result(tu4, "Edit applied successfully.", ts=_ts(base + 4)),
        _assistant(
            model,
            "Added `ExpiredSignatureError` handling — returns HTTP 401 with `token_expired` code.",
            ts=_ts(base + 3), input_tokens=2100, output_tokens=280, cache_read=6500,
        ),
        _user("How should we handle token refresh?", ts=_ts(base + 2), cwd=cwd),
        _assistant(
            model,
            "Use a separate refresh token with a longer TTL stored in an HttpOnly cookie."
            " The access token stays short-lived (15 min); refresh rotates on each use.",
            ts=_ts(base + 2), input_tokens=2200, output_tokens=420, cache_read=7000,
        ),
        _user("Implement the /auth/refresh endpoint", ts=_ts(base + 1), cwd=cwd),
        _assistant(
            model,
            "Implemented `/auth/refresh`: validates the refresh token, issues a new access token,"
            " and rotates the refresh token. Refresh tokens are stored in Redis with a 7-day TTL.",
            ts=_ts(base), input_tokens=2400, output_tokens=650, cache_read=8000,
        ),
    ]
    _write_jsonl(projects_root / "myproject" / f"{sid}.jsonl", records)


def _session_b(projects_root: Path) -> None:
    """myproject — claude-opus-4-6 — thinking blocks — 3 turns."""
    sid = _uid()
    cwd = "/home/user/myproject"
    model = "claude-opus-4-6"
    base = 25

    records = [
        _user(
            "Analyze the performance bottlenecks in the database query layer",
            ts=_ts(base + 6), cwd=cwd, branch="main",
        ),
        _assistant(
            model,
            "The main bottleneck is the N+1 query pattern in `get_user_sessions()`. Each call to"
            " `get_session_details()` in the loop issues a separate SQL query — O(n) round trips"
            " for n sessions.",
            ts=_ts(base + 5), input_tokens=1200, output_tokens=980,
            thinking=(
                "Let me think through the query patterns here. The `get_user_sessions` function"
                " calls `get_session_details` in a loop. Each iteration fires a separate SELECT"
                " on the session_details table. With 500 active users that's 500 queries per"
                " page load. Classic N+1. The fix is a single JOIN or a batch fetch with WHERE"
                " session_id IN (...)."
            ),
        ),
        _user("What indexes would help most?", ts=_ts(base + 4), cwd=cwd),
        _assistant(
            model,
            "Two indexes will cover the hot paths:\n"
            "1. Composite `(user_id, created_at DESC)` on `sessions` — covers the list query"
            " with sort.\n"
            "2. Covering `(session_id, status) INCLUDE (data)` on `session_details` — lets the"
            " batch lookup avoid heap fetches.",
            ts=_ts(base + 3), input_tokens=1800, output_tokens=720,
            thinking=(
                "The query plan shows full table scans on both tables. For `sessions`, the hot"
                " path filters by user_id then sorts by created_at DESC. A composite index on"
                " those two columns in that order will be used for both filter and sort with no"
                " additional sort step."
            ),
        ),
        _user("Generate the migration SQL for those indexes", ts=_ts(base + 1), cwd=cwd),
        _assistant(
            model,
            "```sql\nCREATE INDEX CONCURRENTLY idx_sessions_user_created\n"
            "    ON sessions(user_id, created_at DESC);\n\n"
            "CREATE INDEX CONCURRENTLY idx_session_details_covering\n"
            "    ON session_details(session_id, status) INCLUDE (data);\n```\n\n"
            "Using `CONCURRENTLY` to avoid table locks during migration on the live database.",
            ts=_ts(base), input_tokens=2100, output_tokens=900,
        ),
    ]
    _write_jsonl(projects_root / "myproject" / f"{sid}.jsonl", records)


def _session_c(projects_root: Path) -> None:
    """api-service — claude-haiku-4-5 — short/cheap — 2 turns."""
    sid = _uid()
    cwd = "/home/user/api-service"
    model = "claude-haiku-4-5"
    base = 8

    records = [
        _user("Write a health check endpoint for FastAPI", ts=_ts(base + 3), cwd=cwd, branch="main"),
        _assistant(
            model,
            '```python\nfrom fastapi import APIRouter\n\nrouter = APIRouter()\n\n'
            '@router.get("/health")\ndef health_check():\n'
            '    return {"status": "ok", "version": "1.0.0"}\n```',
            ts=_ts(base + 2), input_tokens=220, output_tokens=380,
        ),
        _user("Add a database connectivity check too", ts=_ts(base + 1), cwd=cwd),
        _assistant(
            model,
            '```python\nfrom sqlalchemy import text\n\n@router.get("/health")\n'
            "def health_check(db: Session = Depends(get_db)):\n"
            "    try:\n        db.execute(text('SELECT 1'))\n        db_ok = True\n"
            "    except Exception:\n        db_ok = False\n"
            '    status = "ok" if db_ok else "degraded"\n'
            '    return {"status": status, "db": "ok" if db_ok else "error"}\n```',
            ts=_ts(base), input_tokens=400, output_tokens=580,
        ),
    ]
    _write_jsonl(projects_root / "api-service" / f"{sid}.jsonl", records)


def _session_d(projects_root: Path) -> None:
    """api-service — claude-sonnet-4-6 — multi-turn debugging — 6 turns."""
    sid = _uid()
    cwd = "/home/user/api-service"
    model = "claude-sonnet-4-6"
    branch = "feature/rate-limiting"
    base = 50

    tu1, tu2, tu3 = _uid(), _uid(), _uid()

    records = [
        _user(
            "The rate limiter is throwing 429s on every request even when under the limit",
            ts=_ts(base + 14), cwd=cwd, branch=branch,
        ),
        _assistant(
            model,
            "Sounds like the Redis key or TTL logic might be off. Let me check the implementation.",
            ts=_ts(base + 13), input_tokens=600, output_tokens=280, cache_create=4000,
            tool_name="Bash", tool_id=tu1, tool_input={"command": "cat backend/rate_limit.py"},
        ),
        _tool_result(
            tu1,
            "def check_rate_limit(key, limit, window):\n"
            "    count = redis.incr(key)\n"
            "    if count == 1:\n        redis.expire(key, window)\n"
            "    return count > limit",
            ts=_ts(base + 12),
        ),
        _assistant(
            model,
            "Found it. `os.environ.get('RATE_LIMIT', 100)` returns a string `'100'` when the"
            " env var is set — comparing `int > str` raises a TypeError in Python 3. More likely"
            " `RATE_LIMIT` isn't set in dev so it returns `None`, which makes every request"
            " exceed the limit.",
            ts=_ts(base + 12), input_tokens=1200, output_tokens=480, cache_read=4000,
        ),
        _user("The limit is definitely set to 100 in config", ts=_ts(base + 11), cwd=cwd),
        _assistant(
            model,
            "Let me check how the limit is passed into `check_rate_limit`.",
            ts=_ts(base + 10), input_tokens=1400, output_tokens=200, cache_read=5000,
            tool_name="Bash", tool_id=tu2,
            tool_input={"command": "grep -r 'check_rate_limit\\|RATE_LIMIT' backend/ --include='*.py'"},
        ),
        _tool_result(
            tu2,
            "backend/middleware.py:    result = check_rate_limit(key, limit=RATE_LIMIT, window=60)\n"
            "backend/config.py:RATE_LIMIT = os.environ.get('RATE_LIMIT', 100)",
            ts=_ts(base + 9),
        ),
        _assistant(
            model,
            "There it is — `os.environ.get('RATE_LIMIT', 100)` returns the env var as a string"
            " when `RATE_LIMIT` is set, but the default `100` is an int. If the env var is set"
            " to `'100'`, `count > '100'` is always True for any positive integer.",
            ts=_ts(base + 9), input_tokens=1800, output_tokens=650, cache_read=6000,
        ),
        _user("RATE_LIMIT is set in our .env — that explains it", ts=_ts(base + 8), cwd=cwd),
        _assistant(
            model,
            "Fix is one character: `int(os.environ.get('RATE_LIMIT', '100'))`.",
            ts=_ts(base + 7), input_tokens=2000, output_tokens=180, cache_read=7000,
            tool_name="Bash", tool_id=tu3,
            tool_input={"command": "sed -i \"s/get('RATE_LIMIT', 100)/get('RATE_LIMIT', '100'))/\" backend/config.py"},
        ),
        _tool_result(tu3, "", ts=_ts(base + 6)),
        _assistant(
            model,
            "Fixed. Also recommend adding an explicit `int()` cast and a test that sets"
            " `RATE_LIMIT` as a string env var.",
            ts=_ts(base + 6), input_tokens=2100, output_tokens=280, cache_read=8000,
        ),
        _user(
            "Good. Now the limiter works but shared office IPs all hit each other's quota",
            ts=_ts(base + 4), cwd=cwd,
        ),
        _assistant(
            model,
            "Switch the key from IP to `user_id` for authenticated routes. For public endpoints"
            " a hybrid `ip:user_agent` hash reduces NAT collisions without requiring auth.",
            ts=_ts(base + 3), input_tokens=2300, output_tokens=520, cache_read=9000,
        ),
        _user("Implement user_id keying for authenticated routes", ts=_ts(base + 2), cwd=cwd),
        _assistant(
            model,
            "Updated `check_rate_limit` to accept an `identifier` param. Middleware passes"
            " `request.state.user_id` for authenticated routes, falls back to IP for public ones.",
            ts=_ts(base + 1), input_tokens=2500, output_tokens=780, cache_read=10000,
        ),
        _user("Tests still pass?", ts=_ts(base), cwd=cwd),
        _assistant(
            model,
            "Yes — `pytest tests/test_rate_limit.py -v`, 14/14 passed including new user-scoped"
            " tests.",
            ts=_ts(base - 1), input_tokens=2600, output_tokens=220, cache_read=11000,
        ),
    ]
    _write_jsonl(projects_root / "api-service" / f"{sid}.jsonl", records)


def _session_e(projects_root: Path) -> None:
    """data-pipeline — claude-sonnet-4-6 — subagent metadata — 4 turns."""
    sid = _uid()
    cwd = "/home/user/data-pipeline"
    model = "claude-sonnet-4-6"
    base = 35
    agent_id = _uid()

    records = [
        _user(
            "Set up the ETL pipeline for the new Salesforce data source",
            ts=_ts(base + 8), cwd=cwd, branch="main",
        ),
        _assistant(
            model,
            "I'll set up the Salesforce ETL pipeline. Let me explore the existing pipeline"
            " structure and the source schema.",
            ts=_ts(base + 7), input_tokens=700, output_tokens=340, cache_create=1800,
        ),
        _user("The source schema is in docs/salesforce_schema.json", ts=_ts(base + 5), cwd=cwd),
        _assistant(
            model,
            "Got it. Using the schema to generate field mappings and the ingestion job config.",
            ts=_ts(base + 4), input_tokens=1400, output_tokens=680, cache_read=1800,
        ),
        _user(
            "Also handle the custom fields we added last quarter — c_account_tier__c etc.",
            ts=_ts(base + 2), cwd=cwd,
        ),
        _assistant(
            model,
            "Included `c_account_tier__c`, `c_support_tier__c`, and `c_renewal_date__c` in the"
            " mapping. Added a dynamic schema resolver that catches any `__c` suffix fields"
            " automatically so future custom fields don't need code changes.",
            ts=_ts(base + 1), input_tokens=1900, output_tokens=820, cache_read=4000,
        ),
        _user("Run a test ingestion with 100 records to validate", ts=_ts(base), cwd=cwd),
        _assistant(
            model,
            "Test ingestion complete: 100/100 records processed, 0 errors. All custom fields"
            " mapped correctly. Ready to run the full historical backfill.",
            ts=_ts(base - 1), input_tokens=2100, output_tokens=380, cache_read=5500,
        ),
    ]
    _write_jsonl(projects_root / "data-pipeline" / f"{sid}.jsonl", records)

    # Subagent metadata: projects/data-pipeline/{session_id}/subagents/{agent_id}.meta.json
    subagent_dir = projects_root / "data-pipeline" / sid / "subagents"
    subagent_dir.mkdir(parents=True, exist_ok=True)
    (subagent_dir / f"{agent_id}.meta.json").write_text(
        json.dumps({"agentType": "general-purpose"})
    )


def _session_f(projects_root: Path) -> None:
    """data-pipeline — claude-haiku-4-5 — summary block (compacted) — 3 turns."""
    sid = _uid()
    cwd = "/home/user/data-pipeline"
    model = "claude-haiku-4-5"
    base = 45

    records = [
        # Summary block from prior compaction
        {
            "type": "summary",
            "timestamp": _ts(base + 10),
            "summary": (
                "Fixed CSV parsing for tab-delimited files. Updated `parse_csv()` to"
                " auto-detect delimiters using `csv.Sniffer`. Added tests covering comma,"
                " tab, and pipe delimiters — all passing."
            ),
        },
        _user(
            "Continue — the sniffer fails on files with only one column",
            ts=_ts(base + 6), cwd=cwd, branch="fix/csv-parsing",
        ),
        _assistant(
            model,
            "Single-column files give the Sniffer nothing to detect. Fix: try `Sniffer().sniff()`,"
            " catch `csv.Error`, fall back to comma delimiter.",
            ts=_ts(base + 5), input_tokens=320, output_tokens=420,
            cache_read=15000, cache_create=600,
        ),
        _user(
            "Good. Also handle BOM at the start of Excel-exported CSVs",
            ts=_ts(base + 2), cwd=cwd,
        ),
        _assistant(
            model,
            "Open with `encoding='utf-8-sig'` — Python strips the BOM automatically for that"
            " codec. No manual stripping needed.",
            ts=_ts(base + 1), input_tokens=560, output_tokens=280, cache_read=16000,
        ),
        _user("Run the full CSV test suite", ts=_ts(base), cwd=cwd),
        _assistant(
            model,
            "All 18 CSV tests pass: comma, tab, pipe, single-column, BOM, and empty-file cases"
            " all covered.",
            ts=_ts(base - 1), input_tokens=700, output_tokens=220, cache_read=16500,
        ),
    ]
    _write_jsonl(projects_root / "data-pipeline" / f"{sid}.jsonl", records)


# ─── Public API ──────────────────────────────────────────────────────────────


def generate(output_dir: str | Path) -> Path:
    """Generate fixture JSONL session files under ``output_dir/projects/``.

    Creates 6 sessions across 3 projects with varied models, turn counts,
    and features (tool use, thinking blocks, subagent metadata, summary block).
    All timestamps are relative to the current time so sessions are always
    visible in the 1h and 1d UI time-range views.

    Args:
        output_dir: Root directory. A ``projects/`` subdirectory is created here.

    Returns:
        Path to the projects root (``output_dir/projects/``).
    """
    projects_root = Path(output_dir) / "projects"
    projects_root.mkdir(parents=True, exist_ok=True)

    _session_a(projects_root)
    _session_b(projects_root)
    _session_c(projects_root)
    _session_d(projects_root)
    _session_e(projects_root)
    _session_f(projects_root)

    return projects_root


# ─── CLI ─────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate Claude session fixture data for testing and demo use."
    )
    parser.add_argument(
        "--output-dir",
        default="/tmp/claude-demo",
        type=Path,
        metavar="PATH",
        help="Root output directory (default: /tmp/claude-demo). Projects go in PATH/projects/.",
    )
    args = parser.parse_args()
    projects_root = generate(args.output_dir)
    print(f"Generated 6 fixture sessions in {projects_root}")


if __name__ == "__main__":
    main()
