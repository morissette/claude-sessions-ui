"""Unit tests for backend.py pure functions."""

import json
import time
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


# ─── FastAPI endpoints ────────────────────────────────────────────────────────

from fastapi.testclient import TestClient

client = TestClient(backend.app)


class TestApiEndpoints:
    def test_sessions_endpoint_returns_200(self, tmp_path, monkeypatch):
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

    def test_sessions_endpoint_empty_dir(self, tmp_path, monkeypatch):
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

    def test_summarize_returns_404_for_unknown_session(self, tmp_path, monkeypatch):
        monkeypatch.setattr(backend, "CLAUDE_DIR", tmp_path / "projects")
        monkeypatch.setattr(backend, "SUMMARIES_DIR", tmp_path / "summaries")
        monkeypatch.setattr(backend, "SAVINGS_FILE", tmp_path / "savings.jsonl")
        monkeypatch.setattr(backend, "TRUNCATION_SAVINGS_FILE", tmp_path / "trunc.jsonl")
        (tmp_path / "summaries").mkdir()
        response = client.post("/api/sessions/doesnotexist/summarize")
        assert response.status_code == 404

    def test_metrics_endpoint_returns_prometheus_text(self):
        response = client.get("/metrics")
        assert response.status_code == 200
        assert "claude_sessions_total" in response.text
