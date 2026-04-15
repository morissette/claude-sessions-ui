"""Unit tests for backend.py pure functions."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import backend


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_jsonl(tmp_path: Path, lines: list[dict], name: str = "session.jsonl") -> Path:
    p = tmp_path / name
    p.write_text("\n".join(json.dumps(l) for l in lines) + "\n")
    return p


# ─── Cost calculation ─────────────────────────────────────────────────────────

class TestModelPricing:
    def test_known_model_haiku(self):
        pricing = backend.MODEL_PRICING["claude-haiku-4-5"]
        assert pricing["input"] == 0.80
        assert pricing["output"] == 4.00
        assert pricing["cache_write"] == 1.00
        assert pricing["cache_read"] == 0.08

    def test_known_model_sonnet(self):
        pricing = backend.MODEL_PRICING["claude-sonnet-4-6"]
        assert pricing["input"] == 3.00
        assert pricing["output"] == 15.00

    def test_default_pricing_exists(self):
        assert "default" in backend.MODEL_PRICING

    def test_all_models_have_required_keys(self):
        required = {"input", "output", "cache_write", "cache_read"}
        for model, pricing in backend.MODEL_PRICING.items():
            assert required <= set(pricing.keys()), f"{model} missing pricing keys"


# ─── get_session_cwd ──────────────────────────────────────────────────────────

class TestGetSessionCwd:
    def test_returns_cwd_from_first_line(self, tmp_path):
        backend._cwd_cache.clear()
        jsonl = make_jsonl(tmp_path, [{"cwd": "/home/user/project", "type": "user"}])
        assert backend.get_session_cwd(jsonl) == "/home/user/project"

    def test_returns_none_for_missing_cwd(self, tmp_path):
        backend._cwd_cache.clear()
        jsonl = make_jsonl(tmp_path, [{"type": "user", "message": "hi"}])
        assert backend.get_session_cwd(jsonl) is None

    def test_returns_none_for_nonexistent_file(self, tmp_path):
        result = backend.get_session_cwd(tmp_path / "nonexistent.jsonl")
        assert result is None

    def test_caches_result(self, tmp_path):
        backend._cwd_cache.clear()
        jsonl = make_jsonl(tmp_path, [{"cwd": "/my/project"}])
        backend.get_session_cwd(jsonl)
        key = str(jsonl)
        assert key in backend._cwd_cache
        assert backend._cwd_cache[key][1] == "/my/project"

    def test_skips_invalid_json_lines(self, tmp_path):
        backend._cwd_cache.clear()
        p = tmp_path / "bad.jsonl"
        p.write_text('not json\n{"cwd": "/found/it"}\n')
        assert backend.get_session_cwd(p) == "/found/it"


# ─── parse_session_file ───────────────────────────────────────────────────────

class TestParseSessionFile:
    def _user_msg(self, text, timestamp=None):
        return {
            "type": "user",
            "timestamp": timestamp or "2024-01-01T10:00:00Z",
            "message": {"content": text},
        }

    def _assistant_msg(self, model="claude-sonnet-4-6", input_tokens=100, output_tokens=50,
                       cache_create=0, cache_read=0, timestamp=None):
        return {
            "type": "assistant",
            "timestamp": timestamp or "2024-01-01T10:00:01Z",
            "message": {
                "model": model,
                "usage": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cache_creation_input_tokens": cache_create,
                    "cache_read_input_tokens": cache_read,
                },
                "content": [],
            },
        }

    def test_returns_none_for_nonexistent_file(self, tmp_path):
        backend._session_cache.clear()
        result = backend.parse_session_file(tmp_path / "ghost.jsonl", "/project")
        assert result is None

    def test_basic_session_parsed(self, tmp_path):
        backend._session_cache.clear()
        jsonl = make_jsonl(tmp_path, [
            self._user_msg("Fix the login bug"),
            self._assistant_msg(),
        ], name="abc123.jsonl")
        result = backend.parse_session_file(jsonl, "/my/project")
        assert result is not None
        assert result["title"] == "Fix the login bug"
        assert result["model"] == "claude-sonnet-4-6"
        assert result["session_id"] == "abc123"
        assert result["project_path"] == "/my/project"

    def test_token_aggregation(self, tmp_path):
        backend._session_cache.clear()
        jsonl = make_jsonl(tmp_path, [
            self._user_msg("task 1", "2024-01-01T10:00:00Z"),
            self._assistant_msg(input_tokens=100, output_tokens=50, cache_create=200, cache_read=300),
            self._user_msg("task 2", "2024-01-01T10:01:00Z"),
            self._assistant_msg(input_tokens=50, output_tokens=25),
        ], name="tok.jsonl")
        result = backend.parse_session_file(jsonl, "/p")
        assert result["stats"]["input_tokens"] == 150
        assert result["stats"]["output_tokens"] == 75
        assert result["stats"]["cache_create_tokens"] == 200
        assert result["stats"]["cache_read_tokens"] == 300
        assert result["stats"]["total_tokens"] == 725

    def test_cost_calculation_haiku(self, tmp_path):
        backend._session_cache.clear()
        # 1M input + 1M output at haiku prices = $0.80 + $4.00 = $4.80
        jsonl = make_jsonl(tmp_path, [
            self._user_msg("task"),
            self._assistant_msg(
                model="claude-haiku-4-5",
                input_tokens=1_000_000,
                output_tokens=1_000_000,
            ),
        ], name="haiku_cost.jsonl")
        result = backend.parse_session_file(jsonl, "/p")
        assert abs(result["stats"]["estimated_cost_usd"] - 4.80) < 0.001

    def test_turn_counting(self, tmp_path):
        backend._session_cache.clear()
        jsonl = make_jsonl(tmp_path, [
            self._user_msg("turn 1"),
            self._assistant_msg(),
            self._user_msg("turn 2"),
            self._assistant_msg(),
            self._user_msg("turn 3"),
        ], name="turns.jsonl")
        result = backend.parse_session_file(jsonl, "/p")
        assert result["turns"] == 3

    def test_first_user_text_captured(self, tmp_path):
        backend._session_cache.clear()
        jsonl = make_jsonl(tmp_path, [
            self._user_msg("First message here"),
            self._assistant_msg(),
            self._user_msg("Second message"),
        ], name="firsttext.jsonl")
        result = backend.parse_session_file(jsonl, "/p")
        assert result["title"] == "First message here"

    def test_git_branch_extracted(self, tmp_path):
        backend._session_cache.clear()
        jsonl = make_jsonl(tmp_path, [
            {"type": "user", "timestamp": "2024-01-01T00:00:00Z",
             "gitBranch": "feature/my-branch",
             "message": {"content": "hello"}},
        ], name="branch.jsonl")
        result = backend.parse_session_file(jsonl, "/p")
        assert result["git_branch"] == "feature/my-branch"

    def test_untitled_session_fallback(self, tmp_path):
        backend._session_cache.clear()
        jsonl = make_jsonl(tmp_path, [
            self._assistant_msg(),
        ], name="notitle.jsonl")
        result = backend.parse_session_file(jsonl, "/p")
        assert result["title"] == "Untitled session"

    def test_mtime_cache_hit(self, tmp_path):
        backend._session_cache.clear()
        jsonl = make_jsonl(tmp_path, [self._user_msg("hello"), self._assistant_msg()],
                           name="cached.jsonl")
        r1 = backend.parse_session_file(jsonl, "/p")
        r2 = backend.parse_session_file(jsonl, "/p")
        assert r1 is r2  # same object from cache

    def test_skips_malformed_lines(self, tmp_path):
        backend._session_cache.clear()
        p = tmp_path / "malformed.jsonl"
        p.write_text('not json\n\n' + json.dumps(self._user_msg("valid")) + "\n")
        result = backend.parse_session_file(p, "/p")
        assert result is not None
        assert result["title"] == "valid"

    def test_tool_use_not_counted_as_turn(self, tmp_path):
        """Messages with tool_result content should not increment turns."""
        backend._session_cache.clear()
        tool_result_msg = {
            "type": "user",
            "timestamp": "2024-01-01T00:00:00Z",
            "message": {
                "content": [{"type": "tool_result", "tool_use_id": "x", "content": "output"}]
            },
        }
        jsonl = make_jsonl(tmp_path, [
            self._user_msg("real turn"),
            self._assistant_msg(),
            tool_result_msg,
        ], name="toolresult.jsonl")
        result = backend.parse_session_file(jsonl, "/p")
        assert result["turns"] == 1


# ─── compute_global_stats ─────────────────────────────────────────────────────

class TestComputeGlobalStats:
    def _session(self, cost=1.0, tokens=1000, input_t=100, output_t=200,
                 cache_create=300, cache_read=400, turns=5, subagents=2,
                 is_active=False, last_active="2000-01-01T00:00:00"):
        return {
            "is_active": is_active,
            "last_active": last_active,
            "turns": turns,
            "subagent_count": subagents,
            "stats": {
                "estimated_cost_usd": cost,
                "total_tokens": tokens,
                "input_tokens": input_t,
                "output_tokens": output_t,
                "cache_create_tokens": cache_create,
                "cache_read_tokens": cache_read,
            },
        }

    def test_empty_sessions(self):
        stats = backend.compute_global_stats([])
        assert stats["total_sessions"] == 0
        assert stats["active_sessions"] == 0
        assert stats["total_cost_usd"] == 0.0
        assert stats["total_tokens"] == 0

    def test_counts_active_sessions(self):
        sessions = [
            self._session(is_active=True),
            self._session(is_active=True),
            self._session(is_active=False),
        ]
        stats = backend.compute_global_stats(sessions)
        assert stats["active_sessions"] == 2
        assert stats["total_sessions"] == 3

    def test_aggregates_tokens(self):
        sessions = [
            self._session(input_t=100, output_t=200, cache_create=50, cache_read=150),
            self._session(input_t=100, output_t=200, cache_create=50, cache_read=150),
        ]
        stats = backend.compute_global_stats(sessions)
        assert stats["total_input_tokens"] == 200
        assert stats["total_output_tokens"] == 400
        assert stats["total_cache_create_tokens"] == 100
        assert stats["total_cache_read_tokens"] == 300

    def test_aggregates_cost(self):
        sessions = [self._session(cost=1.5), self._session(cost=2.5)]
        stats = backend.compute_global_stats(sessions)
        assert stats["total_cost_usd"] == 4.0

    def test_aggregates_turns_and_subagents(self):
        sessions = [self._session(turns=3, subagents=2), self._session(turns=7, subagents=1)]
        stats = backend.compute_global_stats(sessions)
        assert stats["total_turns"] == 10
        assert stats["total_subagents"] == 3


# ─── compute_truncation_savings ───────────────────────────────────────────────

class TestComputeTruncationSavings:
    def test_returns_empty_when_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(backend, "TRUNCATION_SAVINGS_FILE", tmp_path / "nofile.jsonl")
        result = backend.compute_truncation_savings()
        assert result == {"tools": {}, "total_tokens_saved": 0, "total_cost_saved_usd": 0.0}

    def test_aggregates_by_tool(self, tmp_path, monkeypatch):
        f = tmp_path / "trunc.jsonl"
        f.write_text(
            json.dumps({"tool": "Bash", "tokens_saved": 500, "cost_saved_usd": 0.001}) + "\n"
            + json.dumps({"tool": "Bash", "tokens_saved": 300, "cost_saved_usd": 0.0005}) + "\n"
            + json.dumps({"tool": "Read", "tokens_saved": 200, "cost_saved_usd": 0.0003}) + "\n"
        )
        monkeypatch.setattr(backend, "TRUNCATION_SAVINGS_FILE", f)
        result = backend.compute_truncation_savings()
        assert result["tools"]["Bash"]["count"] == 2
        assert result["tools"]["Bash"]["tokens_saved"] == 800
        assert result["tools"]["Read"]["count"] == 1
        assert result["total_tokens_saved"] == 1000

    def test_skips_malformed_lines(self, tmp_path, monkeypatch):
        f = tmp_path / "trunc.jsonl"
        f.write_text("not json\n" + json.dumps({"tool": "Bash", "tokens_saved": 100, "cost_saved_usd": 0.0}) + "\n")
        monkeypatch.setattr(backend, "TRUNCATION_SAVINGS_FILE", f)
        result = backend.compute_truncation_savings()
        assert result["tools"]["Bash"]["count"] == 1


# ─── compute_ollama_savings ───────────────────────────────────────────────────

class TestComputeOllamaSavings:
    def test_returns_zeros_when_no_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(backend, "SAVINGS_FILE", tmp_path / "nofile.jsonl")
        monkeypatch.setattr(backend, "SUMMARIES_DIR", tmp_path / "summaries")
        (tmp_path / "summaries").mkdir()
        result = backend.compute_ollama_savings()
        assert result["pr_skips"] == 0
        assert result["pr_saved_usd"] == 0.0
        assert result["summaries_generated"] == 0

    def test_counts_pr_skips(self, tmp_path, monkeypatch):
        f = tmp_path / "savings.jsonl"
        f.write_text(
            json.dumps({"ts": "t1", "title": "PR 1", "url": "http://a", "saved_usd": 0.05}) + "\n"
            + json.dumps({"ts": "t2", "title": "PR 2", "url": "http://b", "saved_usd": 0.10}) + "\n"
        )
        summaries = tmp_path / "summaries"
        summaries.mkdir()
        monkeypatch.setattr(backend, "SAVINGS_FILE", f)
        monkeypatch.setattr(backend, "SUMMARIES_DIR", summaries)
        result = backend.compute_ollama_savings()
        assert result["pr_skips"] == 2
        assert abs(result["pr_saved_usd"] - 0.15) < 0.0001

    def test_counts_summaries(self, tmp_path, monkeypatch):
        summaries = tmp_path / "summaries"
        summaries.mkdir()
        (summaries / "abc.txt").write_text("summary 1")
        (summaries / "def.txt").write_text("summary 2")
        monkeypatch.setattr(backend, "SAVINGS_FILE", tmp_path / "nofile.jsonl")
        monkeypatch.setattr(backend, "SUMMARIES_DIR", summaries)
        result = backend.compute_ollama_savings()
        assert result["summaries_generated"] == 2
        assert result["summary_saved_usd"] > 0

    def test_recent_skips_capped_at_five(self, tmp_path, monkeypatch):
        f = tmp_path / "savings.jsonl"
        entries = [{"ts": f"t{i}", "title": f"PR {i}", "url": f"http://{i}", "saved_usd": 0.01}
                   for i in range(10)]
        f.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
        summaries = tmp_path / "summaries"
        summaries.mkdir()
        monkeypatch.setattr(backend, "SAVINGS_FILE", f)
        monkeypatch.setattr(backend, "SUMMARIES_DIR", summaries)
        result = backend.compute_ollama_savings()
        assert len(result["recent_skips"]) == 5


# ─── get_cached_summary / cache_summary ──────────────────────────────────────

class TestSummaryCache:
    def test_returns_none_when_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(backend, "SUMMARIES_DIR", tmp_path)
        assert backend.get_cached_summary("nonexistent") is None

    def test_round_trip(self, tmp_path, monkeypatch):
        monkeypatch.setattr(backend, "SUMMARIES_DIR", tmp_path)
        backend.cache_summary("sess123", "Fix the login bug")
        assert backend.get_cached_summary("sess123") == "Fix the login bug"

    def test_returns_none_for_empty_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(backend, "SUMMARIES_DIR", tmp_path)
        (tmp_path / "empty.txt").write_text("   ")
        assert backend.get_cached_summary("empty") is None


# ─── SQLite: init_db ─────────────────────────────────────────────────────────


class TestSQLiteInit:
    def setup_method(self):
        backend._db_conn = None

    def teardown_method(self):
        if backend._db_conn is not None:
            backend._db_conn.close()
            backend._db_conn = None

    def test_init_db_creates_table(self, tmp_path, monkeypatch):
        monkeypatch.setattr(backend, "DB_PATH", tmp_path / "test.db")
        backend.init_db()
        cur = backend._db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'"
        )
        assert cur.fetchone() is not None

    def test_init_db_creates_indexes(self, tmp_path, monkeypatch):
        monkeypatch.setattr(backend, "DB_PATH", tmp_path / "test.db")
        backend.init_db()
        cur = backend._db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_sessions_last_active'"
        )
        assert cur.fetchone() is not None

    def test_init_db_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(backend, "DB_PATH", tmp_path / "test.db")
        backend.init_db()
        backend._db_conn.close()
        backend._db_conn = None
        backend.init_db()  # should not raise
        cur = backend._db_conn.execute("SELECT COUNT(*) FROM sessions")
        assert cur.fetchone()[0] == 0


# ─── SQLite: upsert_sessions_to_db ───────────────────────────────────────────


def _make_session(session_id="abc", turns=3, cost=1.5, last_active=None):
    # Default to 1 hour ago so it's always within any reasonable query window
    recent = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    return {
        "session_id": session_id,
        "project_path": "/my/project",
        "project_name": "project",
        "git_branch": "main",
        "title": "Fix the bug",
        "model": "claude-sonnet-4-6",
        "turns": turns,
        "subagent_count": 0,
        "subagents": [],
        "started_at": (datetime.now(UTC) - timedelta(hours=2)).isoformat(),
        "last_active": last_active or recent,
        "stats": {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_create_tokens": 200,
            "cache_read_tokens": 300,
            "total_tokens": 650,
            "estimated_cost_usd": cost,
        },
        "compact_potential_usd": 0.0,
        "is_active": False,
        "pid": None,
    }


class TestUpsertSessions:
    def setup_method(self):
        backend._db_conn = None

    def teardown_method(self):
        if backend._db_conn is not None:
            backend._db_conn.close()
            backend._db_conn = None

    def test_inserts_new_session(self, tmp_path, monkeypatch):
        monkeypatch.setattr(backend, "DB_PATH", tmp_path / "test.db")
        backend.init_db()
        backend.upsert_sessions_to_db([_make_session("sess1", turns=5)])
        cur = backend._db_conn.execute("SELECT session_id, turns FROM sessions WHERE session_id='sess1'")
        row = cur.fetchone()
        assert row is not None
        assert row[1] == 5

    def test_updates_existing_session(self, tmp_path, monkeypatch):
        monkeypatch.setattr(backend, "DB_PATH", tmp_path / "test.db")
        backend.init_db()
        backend.upsert_sessions_to_db([_make_session("sess1", turns=3)])
        backend.upsert_sessions_to_db([_make_session("sess1", turns=9)])
        cur = backend._db_conn.execute("SELECT turns FROM sessions WHERE session_id='sess1'")
        assert cur.fetchone()[0] == 9

    def test_empty_list_is_noop(self, tmp_path, monkeypatch):
        monkeypatch.setattr(backend, "DB_PATH", tmp_path / "test.db")
        backend.init_db()
        backend.upsert_sessions_to_db([])  # should not raise
        cur = backend._db_conn.execute("SELECT COUNT(*) FROM sessions")
        assert cur.fetchone()[0] == 0

    def test_noop_when_db_not_initialized(self):
        backend._db_conn = None
        backend.upsert_sessions_to_db([_make_session()])  # should not raise


# ─── SQLite: get_sessions_from_db ─────────────────────────────────────────────


class TestGetSessionsFromDb:
    def setup_method(self):
        backend._db_conn = None

    def teardown_method(self):
        if backend._db_conn is not None:
            backend._db_conn.close()
            backend._db_conn = None

    def _init_with_sessions(self, tmp_path, monkeypatch, sessions):
        monkeypatch.setattr(backend, "DB_PATH", tmp_path / "test.db")
        monkeypatch.setattr(backend, "get_cached_summary", lambda session_id: None)
        backend.init_db()
        backend.upsert_sessions_to_db(sessions)

    def test_returns_sessions_within_range(self, tmp_path, monkeypatch):
        recent = _make_session("recent", last_active=datetime.now(UTC).isoformat())
        old = _make_session("old", last_active="2000-01-01T00:00:00+00:00")
        self._init_with_sessions(tmp_path, monkeypatch, [recent, old])
        monkeypatch.setattr(backend, "get_running_claude_processes", lambda: {})
        result = backend.get_sessions_from_db(hours=24)
        ids = [s["session_id"] for s in result]
        assert "recent" in ids
        assert "old" not in ids

    def test_returns_all_required_keys(self, tmp_path, monkeypatch):
        self._init_with_sessions(tmp_path, monkeypatch, [_make_session()])
        monkeypatch.setattr(backend, "get_running_claude_processes", lambda: {})
        result = backend.get_sessions_from_db(hours=24)
        assert len(result) == 1
        s = result[0]
        for key in ("session_id", "project_path", "project_name", "title", "model",
                    "turns", "stats", "is_active", "pid", "started_at", "last_active"):
            assert key in s, f"missing key: {key}"
        assert "estimated_cost_usd" in s["stats"]

    def test_active_session_annotated(self, tmp_path, monkeypatch):
        self._init_with_sessions(tmp_path, monkeypatch, [_make_session("mysess")])
        monkeypatch.setattr(
            backend, "get_running_claude_processes",
            lambda: {99: {"pid": 99, "cwd": None, "session_id": "mysess", "create_time": 0.0}},
        )
        result = backend.get_sessions_from_db(hours=24)
        assert result[0]["is_active"] is True
        assert result[0]["pid"] == 99

    def test_returns_empty_when_db_not_initialized(self, monkeypatch):
        backend._db_conn = None
        result = backend.get_sessions_from_db(hours=24)
        assert result == []

    def test_get_sessions_from_db_no_cutoff(self, tmp_path, monkeypatch):
        """Calling with no hours/start/end should return all rows (no WHERE clause)."""
        recent = _make_session("recent", last_active=datetime.now(UTC).isoformat())
        old = _make_session("old", last_active="2000-01-01T00:00:00+00:00")
        self._init_with_sessions(tmp_path, monkeypatch, [recent, old])
        monkeypatch.setattr(backend, "get_running_claude_processes", lambda: {})
        result = backend.get_sessions_from_db()
        ids = [s["session_id"] for s in result]
        assert "recent" in ids
        assert "old" in ids

    def test_get_sessions_from_db_custom_start_end(self, tmp_path, monkeypatch):
        """Custom start/end filters by last_active range."""
        in_range = _make_session("in_range", last_active="2025-06-15T12:00:00+00:00")
        out_range = _make_session("out_range", last_active="2025-01-01T00:00:00+00:00")
        self._init_with_sessions(tmp_path, monkeypatch, [in_range, out_range])
        monkeypatch.setattr(backend, "get_running_claude_processes", lambda: {})
        result = backend.get_sessions_from_db(
            start="2025-06-01T00:00:00+00:00",
            end="2025-06-30T23:59:59+00:00",
        )
        ids = [s["session_id"] for s in result]
        assert "in_range" in ids
        assert "out_range" not in ids


# ─── get_sessions_for_range ───────────────────────────────────────────────────


class TestGetSessionsForRange:
    def test_short_range_uses_jsonl_path(self, monkeypatch):
        called = {}
        monkeypatch.setattr(backend, "get_all_sessions", lambda hours=24: called.setdefault("jsonl", hours) or [])
        monkeypatch.setattr(backend, "get_sessions_from_db", lambda hours=None, start=None, end=None: called.setdefault("db", hours) or [])
        backend.get_sessions_for_range("1h")
        assert "jsonl" in called
        assert "db" not in called

    def test_1d_uses_jsonl_path(self, monkeypatch):
        called = {}
        monkeypatch.setattr(backend, "get_all_sessions", lambda hours=24: called.setdefault("jsonl", hours) or [])
        monkeypatch.setattr(backend, "get_sessions_from_db", lambda hours=None, start=None, end=None: called.setdefault("db", hours) or [])
        backend.get_sessions_for_range("1d")
        assert "jsonl" in called
        assert "db" not in called

    def test_long_range_uses_db_path(self, monkeypatch):
        called = {}
        monkeypatch.setattr(backend, "get_all_sessions", lambda hours=24: called.setdefault("jsonl", hours) or [])
        monkeypatch.setattr(backend, "get_sessions_from_db", lambda hours=None, start=None, end=None: called.setdefault("db", hours) or [])
        backend.get_sessions_for_range("3d")
        assert "db" in called
        assert "jsonl" not in called

    def test_invalid_range_falls_back_to_1d(self, monkeypatch):
        called = {}
        monkeypatch.setattr(backend, "get_all_sessions", lambda hours=24: called.setdefault("jsonl", hours) or [])
        monkeypatch.setattr(backend, "get_sessions_from_db", lambda hours=None, start=None, end=None: called.setdefault("db", hours) or [])
        backend.get_sessions_for_range("bogus")
        assert "jsonl" in called
        assert called["jsonl"] == 24

    def test_all_valid_ranges_map_to_known_hours(self):
        for key, hours in backend.TIME_RANGE_HOURS.items():
            if key == "all":
                assert hours is None
            else:
                assert isinstance(hours, int)
                assert hours > 0

    def test_time_range_all(self):
        assert backend.TIME_RANGE_HOURS["all"] is None

    def test_all_range_uses_db_path(self, monkeypatch):
        called = {}
        monkeypatch.setattr(backend, "get_all_sessions", lambda hours=24: called.setdefault("jsonl", hours) or [])
        monkeypatch.setattr(backend, "get_sessions_from_db", lambda hours=None, start=None, end=None: called.setdefault("db", hours) or [])
        backend.get_sessions_for_range("all")
        assert "db" in called
        assert "jsonl" not in called

    def test_custom_range_uses_db_path(self, monkeypatch):
        called = {}
        monkeypatch.setattr(backend, "get_all_sessions", lambda hours=24: called.setdefault("jsonl", hours) or [])
        monkeypatch.setattr(backend, "get_sessions_from_db", lambda hours=None, start=None, end=None: called.setdefault("db", (start, end)) or [])
        backend.get_sessions_for_range("1d", start="2025-01-01T00:00:00Z", end="2025-01-07T23:59:59Z")
        assert "db" in called
        assert "jsonl" not in called


# ─── compute_global_stats with time_range_hours ───────────────────────────────


class TestComputeGlobalStatsWithRange:
    def _session(self, cost, last_active):
        return {
            "is_active": False,
            "last_active": last_active,
            "turns": 1,
            "subagent_count": 0,
            "stats": {
                "estimated_cost_usd": cost,
                "total_tokens": 100,
                "input_tokens": 50,
                "output_tokens": 50,
                "cache_create_tokens": 0,
                "cache_read_tokens": 0,
            },
        }

    def test_cost_today_reflects_time_range(self):
        recent = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        old = (datetime.now(UTC) - timedelta(hours=48)).isoformat()
        sessions = [self._session(5.0, recent), self._session(3.0, old)]
        stats = backend.compute_global_stats(sessions, time_range_hours=24)
        assert stats["cost_today_usd"] == 5.0
        assert stats["total_cost_usd"] == 8.0

    def test_wide_range_includes_old_sessions(self):
        old = (datetime.now(UTC) - timedelta(hours=100)).isoformat()
        sessions = [self._session(2.0, old)]
        stats = backend.compute_global_stats(sessions, time_range_hours=168)
        assert stats["cost_today_usd"] == 2.0

    def test_default_24h_excludes_old_sessions(self):
        old = (datetime.now(UTC) - timedelta(hours=48)).isoformat()
        sessions = [self._session(7.0, old)]
        stats = backend.compute_global_stats(sessions)  # default 24h
        assert stats["cost_today_usd"] == 0.0


# ─── FastAPI endpoints ────────────────────────────────────────────────────────

from fastapi.testclient import TestClient


class TestApiEndpoints:
    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        """Create TestClient after patching DB_PATH so lifespan init_db() uses a temp file."""
        monkeypatch.setattr(backend, "DB_PATH", tmp_path / "test.db")
        monkeypatch.setattr(backend, "_db_conn", None)
        with TestClient(backend.app) as c:
            yield c

    def test_sessions_endpoint_returns_200(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(backend, "CLAUDE_DIR", tmp_path / "projects")
        monkeypatch.setattr(backend, "SUMMARIES_DIR", tmp_path / "summaries")
        monkeypatch.setattr(backend, "SAVINGS_FILE", tmp_path / "savings.jsonl")
        monkeypatch.setattr(backend, "TRUNCATION_SAVINGS_FILE", tmp_path / "trunc.jsonl")
        (tmp_path / "summaries").mkdir()
        response = client.get("/api/sessions")
        assert response.status_code == 200
        data = response.json()
        assert "sessions" in data
        assert "stats" in data
        assert "savings" in data
        assert "truncation" in data
        assert "time_range" in data

    def test_sessions_endpoint_accepts_time_range_param(self, client, tmp_path, monkeypatch):
        projects = tmp_path / "projects"
        projects.mkdir()
        monkeypatch.setattr(backend, "CLAUDE_DIR", projects)
        monkeypatch.setattr(backend, "SUMMARIES_DIR", tmp_path / "summaries")
        monkeypatch.setattr(backend, "SAVINGS_FILE", tmp_path / "savings.jsonl")
        monkeypatch.setattr(backend, "TRUNCATION_SAVINGS_FILE", tmp_path / "trunc.jsonl")
        (tmp_path / "summaries").mkdir()
        response = client.get("/api/sessions?time_range=1w")
        assert response.status_code == 200
        assert response.json()["time_range"] == "1w"

    def test_sessions_endpoint_invalid_range_defaults_to_1d(self, client, tmp_path, monkeypatch):
        projects = tmp_path / "projects"
        projects.mkdir()
        monkeypatch.setattr(backend, "CLAUDE_DIR", projects)
        monkeypatch.setattr(backend, "SUMMARIES_DIR", tmp_path / "summaries")
        monkeypatch.setattr(backend, "SAVINGS_FILE", tmp_path / "savings.jsonl")
        monkeypatch.setattr(backend, "TRUNCATION_SAVINGS_FILE", tmp_path / "trunc.jsonl")
        (tmp_path / "summaries").mkdir()
        response = client.get("/api/sessions?time_range=bogus")
        assert response.status_code == 200
        assert response.json()["time_range"] == "1d"

    def test_sessions_endpoint_empty_dir(self, client, tmp_path, monkeypatch):
        projects = tmp_path / "projects"
        projects.mkdir()
        monkeypatch.setattr(backend, "CLAUDE_DIR", projects)
        monkeypatch.setattr(backend, "SUMMARIES_DIR", tmp_path / "summaries")
        monkeypatch.setattr(backend, "SAVINGS_FILE", tmp_path / "savings.jsonl")
        monkeypatch.setattr(backend, "TRUNCATION_SAVINGS_FILE", tmp_path / "trunc.jsonl")
        (tmp_path / "summaries").mkdir()
        response = client.get("/api/sessions")
        assert response.status_code == 200
        assert response.json()["sessions"] == []

    def test_db_status_endpoint_returns_200(self, client):
        response = client.get("/api/db/status")
        assert response.status_code == 200
        data = response.json()
        assert "total_stored" in data
        assert "db_path" in data

    def test_summarize_returns_404_for_unknown_session(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(backend, "CLAUDE_DIR", tmp_path / "projects")
        monkeypatch.setattr(backend, "SUMMARIES_DIR", tmp_path / "summaries")
        monkeypatch.setattr(backend, "SAVINGS_FILE", tmp_path / "savings.jsonl")
        monkeypatch.setattr(backend, "TRUNCATION_SAVINGS_FILE", tmp_path / "trunc.jsonl")
        (tmp_path / "summaries").mkdir()
        response = client.post("/api/sessions/doesnotexist/summarize")
        assert response.status_code == 404

    def test_metrics_endpoint_returns_prometheus_text(self, client):
        response = client.get("/metrics")
        assert response.status_code == 200
        assert "claude_sessions_total" in response.text


# ─── TestSessionDetail ────────────────────────────────────────────────────────


class TestSessionDetail:
    def test_find_session_file_returns_path(self, tmp_path, monkeypatch):
        proj = tmp_path / "projects" / "myproject"
        proj.mkdir(parents=True)
        jsonl = proj / "abc123.jsonl"
        jsonl.write_text("{}\n")
        monkeypatch.setattr(backend, "CLAUDE_DIR", tmp_path / "projects")
        result = backend.find_session_file("abc123")
        assert result == jsonl

    def test_find_session_file_missing_returns_none(self, tmp_path, monkeypatch):
        (tmp_path / "projects").mkdir()
        monkeypatch.setattr(backend, "CLAUDE_DIR", tmp_path / "projects")
        assert backend.find_session_file("nonexistent") is None

    def test_parse_session_detail_user_message(self, tmp_path):
        jsonl = tmp_path / "sess1.jsonl"
        jsonl.write_text(json.dumps({
            "type": "user",
            "timestamp": "2024-01-01T10:00:00Z",
            "message": {"content": "Hello, fix the bug"},
        }) + "\n")
        result = backend.parse_session_detail(jsonl)
        assert result["session_id"] == "sess1"
        assert result["total_messages"] == 1
        msgs = result["messages"]
        assert len(msgs) == 1
        assert msgs[0]["type"] == "user"
        assert msgs[0]["content"] == "Hello, fix the bug"

    def test_parse_session_detail_tool_pairing(self, tmp_path):
        jsonl = tmp_path / "sess2.jsonl"
        lines = [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "tu_1", "name": "Bash", "input": {"command": "ls"}}
            ]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "tu_1", "content": "file.txt"}
            ]}},
        ]
        jsonl.write_text("\n".join(json.dumps(l) for l in lines) + "\n")
        result = backend.parse_session_detail(jsonl)
        tool_results = [m for m in result["messages"] if m["type"] == "tool_result"]
        assert len(tool_results) == 1
        assert tool_results[0]["tool_name"] == "Bash"
        assert tool_results[0]["tool_use_id"] == "tu_1"

    def test_parse_session_detail_pagination(self, tmp_path):
        jsonl = tmp_path / "sess3.jsonl"
        lines = [{"type": "user", "message": {"content": f"msg {i}"}} for i in range(10)]
        jsonl.write_text("\n".join(json.dumps(l) for l in lines) + "\n")
        result = backend.parse_session_detail(jsonl, offset=5, limit=3)
        assert result["total_messages"] == 10
        assert result["offset"] == 5
        assert len(result["messages"]) == 3
        assert result["messages"][0]["content"] == "msg 5"

    def test_detail_endpoint_404_unknown_session(self, tmp_path, monkeypatch):
        monkeypatch.setattr(backend, "DB_PATH", tmp_path / "test.db")
        monkeypatch.setattr(backend, "_db_conn", None)
        monkeypatch.setattr(backend, "CLAUDE_DIR", tmp_path / "projects")
        (tmp_path / "projects").mkdir()
        with TestClient(backend.app) as client:
            response = client.get("/api/sessions/doesnotexist/detail")
        assert response.status_code == 404


# ─── TestExportSkill ──────────────────────────────────────────────────────────


class TestExportSkill:
    def test_slugify_simple_title(self):
        assert backend.slugify_skill_name("Debug TS Errors") == "debug-ts-errors"

    def test_slugify_strips_special_chars(self):
        result = backend.slugify_skill_name("Fix: auth/login (bug)")
        assert ":" not in result
        assert "/" not in result
        assert "(" not in result

    def test_slugify_truncates_long_names(self):
        long_title = "a" * 100
        result = backend.slugify_skill_name(long_title)
        assert len(result) <= 60

    def test_slugify_empty_fallback(self):
        assert backend.slugify_skill_name("") == "untitled-skill"

    def test_extract_skill_data_tools(self, tmp_path):
        jsonl = tmp_path / "sess.jsonl"
        lines = [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "t1", "name": "Bash", "input": {}},
                {"type": "tool_use", "id": "t2", "name": "Read", "input": {}},
            ]}},
        ]
        jsonl.write_text("\n".join(json.dumps(l) for l in lines) + "\n")
        data = backend.extract_session_skill_data(jsonl)
        assert "Bash" in data["tools_used"]
        assert "Read" in data["tools_used"]

    def test_extract_skill_data_messages(self, tmp_path):
        jsonl = tmp_path / "sess.jsonl"
        lines = [
            {"type": "user", "message": {"content": "fix the login bug"}},
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": "Done, fixed it."}
            ]}},
        ]
        jsonl.write_text("\n".join(json.dumps(l) for l in lines) + "\n")
        data = backend.extract_session_skill_data(jsonl)
        assert data["first_user_message"] == "fix the login bug"
        assert "Done" in data["last_assistant_message"]

    def test_resolve_skill_path_no_conflict(self, tmp_path, monkeypatch):
        monkeypatch.setattr(backend, "SKILLS_DIR", tmp_path)
        path = backend.resolve_skill_path("my-skill", "global")
        assert path == tmp_path / "my-skill.md"

    def test_resolve_skill_path_conflict(self, tmp_path, monkeypatch):
        monkeypatch.setattr(backend, "SKILLS_DIR", tmp_path)
        (tmp_path / "my-skill.md").write_text("existing")
        path = backend.resolve_skill_path("my-skill", "global")
        assert path == tmp_path / "my-skill-2.md"

    def test_template_generate_skill_returns_tuple(self, tmp_path):
        data = {
            "title": "Fix auth bug",
            "tools_used": ["Bash", "Edit"],
            "first_user_message": "fix the login",
            "last_assistant_message": "fixed",
        }
        name, body = backend.template_generate_skill(data)
        assert isinstance(name, str)
        assert isinstance(body, str)
        assert len(name) > 0
        assert len(body) > 0

    def test_export_endpoint_creates_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(backend, "DB_PATH", tmp_path / "test.db")
        monkeypatch.setattr(backend, "_db_conn", None)
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        monkeypatch.setattr(backend, "SKILLS_DIR", skills_dir)
        proj = tmp_path / "projects" / "proj"
        proj.mkdir(parents=True)
        jsonl = proj / "mysess.jsonl"
        jsonl.write_text(json.dumps({
            "type": "user",
            "message": {"content": "fix the bug"},
        }) + "\n")
        monkeypatch.setattr(backend, "CLAUDE_DIR", tmp_path / "projects")
        monkeypatch.setattr(backend, "ollama_is_available", lambda: False)
        with TestClient(backend.app) as client:
            response = client.post("/api/sessions/mysess/export-skill?scope=global")
        assert response.status_code == 200
        data = response.json()
        assert "skill_name" in data
        assert Path(data["skill_path"]).exists()

    def test_export_endpoint_404_unknown_session(self, tmp_path, monkeypatch):
        monkeypatch.setattr(backend, "DB_PATH", tmp_path / "test.db")
        monkeypatch.setattr(backend, "_db_conn", None)
        monkeypatch.setattr(backend, "CLAUDE_DIR", tmp_path / "projects")
        (tmp_path / "projects").mkdir()
        with TestClient(backend.app) as client:
            response = client.post("/api/sessions/doesnotexist/export-skill")
        assert response.status_code == 404
