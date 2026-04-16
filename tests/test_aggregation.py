"""Tests for backend.aggregation — global stats, project stats, session routing."""

import json
from datetime import UTC, datetime, timedelta

import backend
from backend import aggregation, constants

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


# ─── compute_project_stats ────────────────────────────────────────────────────

def test_compute_project_stats_groups_correctly():
    sessions = [
        {
            "project_name": "proj-a",
            "project_path": "/proj-a",
            "stats": {"estimated_cost_usd": 1.0, "total_tokens": 100, "input_tokens": 60, "output_tokens": 40},
            "model": "claude-sonnet-4-6",
            "started_at": "2026-04-01T00:00:00",
            "last_active": "2026-04-01T01:00:00",
        },
        {
            "project_name": "proj-a",
            "project_path": "/proj-a",
            "stats": {"estimated_cost_usd": 2.0, "total_tokens": 200, "input_tokens": 120, "output_tokens": 80},
            "model": "claude-opus-4-6",
            "started_at": "2026-04-01T02:00:00",
            "last_active": "2026-04-01T03:00:00",
        },
        {
            "project_name": "proj-b",
            "project_path": "/proj-b",
            "stats": {"estimated_cost_usd": 0.5, "total_tokens": 50, "input_tokens": 30, "output_tokens": 20},
            "model": "claude-haiku-4-5-20251001",
            "started_at": "2026-04-01T00:00:00",
            "last_active": "2026-04-01T00:30:00",
        },
    ]
    result = backend.compute_project_stats(sessions)
    assert len(result) == 2
    proj_a = next(p for p in result if p["project_name"] == "proj-a")
    assert proj_a["session_count"] == 2
    assert abs(proj_a["total_cost_usd"] - 3.0) < 0.001
    assert proj_a["first_session"] == "2026-04-01T00:00:00"
    assert proj_a["last_session"] == "2026-04-01T03:00:00"


def test_compute_project_stats_empty():
    assert backend.compute_project_stats([]) == []


def test_compute_project_stats_mixed_timestamps():
    """Groups correctly when sessions mix Z and +00:00 timestamp suffixes."""
    sessions = [
        {
            "project_path": "/proj-a",
            "project_name": "proj-a",
            "stats": {"estimated_cost_usd": 1.0, "total_tokens": 100},
            "model": "claude-sonnet-4-6",
            "started_at": "2026-04-01T00:00:00Z",
            "last_active": "2026-04-01T01:00:00+00:00",
        },
        {
            "project_path": "/proj-a",
            "project_name": "proj-a",
            "stats": {"estimated_cost_usd": 2.0, "total_tokens": 200},
            "model": "claude-opus-4-6",
            "started_at": "2026-04-01T02:00:00+00:00",
            "last_active": "2026-04-01T03:00:00Z",
        },
    ]
    result = backend.compute_project_stats(sessions)
    assert len(result) == 1
    p = result[0]
    # first_session must be <= last_session after normalizing Z vs +00:00
    assert p["first_session"].replace("Z", "+00:00") <= p["last_session"].replace("Z", "+00:00")


# ─── get_global_tool_usage ────────────────────────────────────────────────────

def _write_jsonl(path, entries):
    """Write a list of dicts as newline-delimited JSON."""
    path.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")


def _tool_use_entry(tool_names):
    """Build a minimal assistant message entry with tool_use blocks."""
    return {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "tool_use", "name": name}
                for name in tool_names
            ]
        },
    }


class TestGetGlobalToolUsage:
    def test_counts_tool_use_blocks(self, tmp_path, monkeypatch):
        """Counts tool_use blocks correctly across sessions."""
        proj = tmp_path / "proj"
        proj.mkdir()
        sid = "abc123"
        _write_jsonl(proj / f"{sid}.jsonl", [
            _tool_use_entry(["Read", "Edit"]),
            _tool_use_entry(["Read"]),
            {"type": "user", "message": {"content": [{"type": "tool_use", "name": "Ignored"}]}},
        ])
        monkeypatch.setattr(constants, "CLAUDE_DIR", tmp_path)
        sessions = [{"session_id": sid}]
        result = aggregation.get_global_tool_usage(sessions)
        counts = {r["tool"]: r["count"] for r in result}
        assert counts["Read"] == 2
        assert counts["Edit"] == 1
        assert "Ignored" not in counts

    def test_sorted_by_count_descending(self, tmp_path, monkeypatch):
        """Results are ordered most-used first."""
        proj = tmp_path / "proj"
        proj.mkdir()
        sid = "def456"
        _write_jsonl(proj / f"{sid}.jsonl", [
            _tool_use_entry(["A", "A", "A", "B", "B", "C"]),
        ])
        monkeypatch.setattr(constants, "CLAUDE_DIR", tmp_path)
        result = aggregation.get_global_tool_usage([{"session_id": sid}])
        assert result[0]["tool"] == "A"
        assert result[1]["tool"] == "B"
        assert result[2]["tool"] == "C"

    def test_malformed_lines_skipped(self, tmp_path, monkeypatch):
        """Lines that are not valid JSON are silently skipped."""
        proj = tmp_path / "proj"
        proj.mkdir()
        sid = "ghi789"
        content = 'not json\n' + json.dumps(_tool_use_entry(["Bash"])) + '\n{bad}'
        (proj / f"{sid}.jsonl").write_text(content, encoding="utf-8")
        monkeypatch.setattr(constants, "CLAUDE_DIR", tmp_path)
        result = aggregation.get_global_tool_usage([{"session_id": sid}])
        assert result == [{"tool": "Bash", "count": 1}]

    def test_missing_session_file_skipped(self, tmp_path, monkeypatch):
        """Session with no matching JSONL file is skipped without error."""
        monkeypatch.setattr(constants, "CLAUDE_DIR", tmp_path)
        result = aggregation.get_global_tool_usage([{"session_id": "nonexistent-session"}])
        assert result == []

    def test_missing_tool_name_uses_unknown(self, tmp_path, monkeypatch):
        """tool_use block with no 'name' key falls back to 'Unknown'."""
        proj = tmp_path / "proj"
        proj.mkdir()
        sid = "jkl012"
        _write_jsonl(proj / f"{sid}.jsonl", [
            {"type": "assistant", "message": {"content": [{"type": "tool_use"}]}},
        ])
        monkeypatch.setattr(constants, "CLAUDE_DIR", tmp_path)
        result = aggregation.get_global_tool_usage([{"session_id": sid}])
        assert result == [{"tool": "Unknown", "count": 1}]

    def test_respects_limit(self, tmp_path, monkeypatch):
        """Returns at most `limit` tools."""
        proj = tmp_path / "proj"
        proj.mkdir()
        sid = "mno345"
        tools = [chr(ord("A") + i) for i in range(10)]
        _write_jsonl(proj / f"{sid}.jsonl", [_tool_use_entry(tools)])
        monkeypatch.setattr(constants, "CLAUDE_DIR", tmp_path)
        result = aggregation.get_global_tool_usage([{"session_id": sid}], limit=3)
        assert len(result) == 3
