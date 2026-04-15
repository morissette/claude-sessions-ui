"""Tests for backend.aggregation — global stats, project stats, session routing."""

from datetime import UTC, datetime, timedelta

import backend

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
