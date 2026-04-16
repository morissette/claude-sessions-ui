"""Tests for backend routes — API endpoints, search, trends, projects, batch ops."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import backend

# ─── FastAPI endpoints ────────────────────────────────────────────────────────

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


# ─── Search endpoint ──────────────────────────────────────────────────────────

def test_search_empty_query(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(backend, "_db_conn", None)
    with TestClient(backend.app) as client:
        resp = client.get("/api/search?q=&time_range=1d")
    assert resp.status_code == 200
    data = resp.json()
    assert data["results"] == []
    assert data["total"] == 0


# ─── Trends endpoint ─────────────────────────────────────────────────────────

def test_get_trends_returns_list(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(backend, "_db_conn", None)
    with TestClient(backend.app) as client:
        resp = client.get("/api/trends?range=4w")
        assert resp.status_code == 200
        body = resp.json()
        assert "days" in body
        assert isinstance(body["days"], list)


# ─── Projects endpoint ────────────────────────────────────────────────────────

def test_api_projects_returns_list(tmp_path, monkeypatch):
    """GET /api/projects returns a JSON list."""
    monkeypatch.setattr(backend, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(backend, "_db_conn", None)
    monkeypatch.setattr(backend, "CLAUDE_DIR", tmp_path / "projects")
    (tmp_path / "projects").mkdir()
    with TestClient(backend.app) as client:
        resp = client.get("/api/projects?time_range=1d")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


# ─── Cost week in global stats ────────────────────────────────────────────────

def test_cost_week_usd_in_global_stats(tmp_path):
    now = datetime.now(UTC)
    recent = (now - timedelta(days=3)).isoformat()
    old = (now - timedelta(days=10)).isoformat()
    sessions = [
        {"stats": {"estimated_cost_usd": 5.0, "total_tokens": 100, "input_tokens": 50, "output_tokens": 50, "cache_create_tokens": 0, "cache_read_tokens": 0}, "last_active": recent, "is_active": False, "model": "claude-sonnet-4-6", "turns": 1, "subagent_count": 0},
        {"stats": {"estimated_cost_usd": 3.0, "total_tokens": 100, "input_tokens": 50, "output_tokens": 50, "cache_create_tokens": 0, "cache_read_tokens": 0}, "last_active": old, "is_active": False, "model": "claude-sonnet-4-6", "turns": 1, "subagent_count": 0},
    ]
    stats = backend.compute_global_stats(sessions, 24 * 30)
    assert stats["cost_week_usd"] == 5.0


# ─── Batch Operations ────────────────────────────────────────────────────────

def test_batch_export_empty_session_ids():
    with TestClient(backend.app) as client:
        resp = client.post("/api/batch/export", json={"session_ids": []})
    assert resp.status_code == 400


def test_batch_export_invalid_session_id():
    with TestClient(backend.app) as client:
        resp = client.post("/api/batch/export", json={"session_ids": ["../etc/passwd"]})
    assert resp.status_code == 400


def test_batch_cost_report_empty():
    with TestClient(backend.app) as client:
        resp = client.post("/api/batch/cost-report", json={"session_ids": []})
    assert resp.status_code == 400


def test_batch_cost_report_returns_csv_headers():
    with TestClient(backend.app) as client:
        resp = client.post("/api/batch/cost-report", json={"session_ids": ["nonexistent-session-abc"]})
    assert resp.status_code == 200
    assert "session_id" in resp.text


def test_batch_summarize_empty_session_ids():
    with TestClient(backend.app) as client:
        resp = client.post("/api/batch/summarize", json={"session_ids": []})
    assert resp.status_code == 400


def test_batch_summarize_invalid_session_id():
    with TestClient(backend.app) as client:
        resp = client.post("/api/batch/summarize", json={"session_ids": ["../path/traversal"]})
    assert resp.status_code == 400


# ─── Analytics endpoint ───────────────────────────────────────────────────────

def test_analytics_endpoint_returns_200(tmp_path, monkeypatch):
    """GET /api/analytics returns 200 with expected session_metrics keys."""
    monkeypatch.setattr(backend, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(backend, "_db_conn", None)
    monkeypatch.setattr(backend, "CLAUDE_DIR", tmp_path / "projects")
    (tmp_path / "projects").mkdir()
    with TestClient(backend.app) as client:
        resp = client.get("/api/analytics?time_range=1d")
    assert resp.status_code == 200
    data = resp.json()
    assert "session_metrics" in data
    sm = data["session_metrics"]
    for key in [
        "total_wall_time_seconds",
        "estimated_time_saved_hours",
        "cache_efficiency_pct",
        "cache_savings_usd",
        "avg_cost_per_turn",
        "avg_tokens_per_turn",
        "longest_sessions",
        "most_expensive_sessions",
        "most_turns_sessions",
        "most_subagents_sessions",
        "projects_by_sessions",
        "projects_by_cost",
        "model_distribution",
        "active_hours",
        "top_tools",
    ]:
        assert key in sm, f"Missing key: {key}"
    assert len(sm["active_hours"]) == 24
    assert all("hour" in h and "count" in h for h in sm["active_hours"])


def test_analytics_invalid_range_defaults(tmp_path, monkeypatch):
    """GET /api/analytics with unknown range defaults to 1d without 500."""
    monkeypatch.setattr(backend, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(backend, "_db_conn", None)
    monkeypatch.setattr(backend, "CLAUDE_DIR", tmp_path / "projects")
    (tmp_path / "projects").mkdir()
    with TestClient(backend.app) as client:
        resp = client.get("/api/analytics?time_range=invalid")
    assert resp.status_code == 200
