"""Tests for backend.database — SQLite init, upsert, queries; and get_sessions_for_range."""

from datetime import UTC, datetime, timedelta

import backend
import backend.process  # noqa: F401 — needed so backend.process is patchable in tests

# ─── Helpers ──────────────────────────────────────────────────────────────────

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
        monkeypatch.setattr(backend.process, "get_running_claude_processes", lambda: {})
        result = backend.get_sessions_from_db(hours=24)
        ids = [s["session_id"] for s in result]
        assert "recent" in ids
        assert "old" not in ids

    def test_returns_all_required_keys(self, tmp_path, monkeypatch):
        self._init_with_sessions(tmp_path, monkeypatch, [_make_session()])
        monkeypatch.setattr(backend.process, "get_running_claude_processes", lambda: {})
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
            backend.process, "get_running_claude_processes",
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
        monkeypatch.setattr(backend.process, "get_running_claude_processes", lambda: {})
        result = backend.get_sessions_from_db()
        ids = [s["session_id"] for s in result]
        assert "recent" in ids
        assert "old" in ids

    def test_get_sessions_from_db_custom_start_end(self, tmp_path, monkeypatch):
        """Custom start/end filters by last_active range."""
        in_range = _make_session("in_range", last_active="2025-06-15T12:00:00+00:00")
        out_range = _make_session("out_range", last_active="2025-01-01T00:00:00+00:00")
        self._init_with_sessions(tmp_path, monkeypatch, [in_range, out_range])
        monkeypatch.setattr(backend.process, "get_running_claude_processes", lambda: {})
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
