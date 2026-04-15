"""Tests for backend.parsing — JSONL parsing and mtime-based caching."""

import json
from pathlib import Path

import backend

# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_jsonl(tmp_path: Path, lines: list[dict], name: str = "session.jsonl") -> Path:
    p = tmp_path / name
    p.write_text("\n".join(json.dumps(row) for row in lines) + "\n")
    return p


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
