"""Tests for backend.ollama — truncation savings, Ollama savings, summary cache."""

import json

import backend

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
