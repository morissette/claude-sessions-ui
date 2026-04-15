"""Tests for backend.detail — session detail parsing, find_session_file, analytics."""

import json

from fastapi.testclient import TestClient

import backend

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
        jsonl.write_text("\n".join(json.dumps(row) for row in lines) + "\n")
        result = backend.parse_session_detail(jsonl)
        tool_results = [m for m in result["messages"] if m["type"] == "tool_result"]
        assert len(tool_results) == 1
        assert tool_results[0]["tool_name"] == "Bash"
        assert tool_results[0]["tool_use_id"] == "tu_1"

    def test_parse_session_detail_pagination(self, tmp_path):
        jsonl = tmp_path / "sess3.jsonl"
        lines = [{"type": "user", "message": {"content": f"msg {i}"}} for i in range(10)]
        jsonl.write_text("\n".join(json.dumps(row) for row in lines) + "\n")
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


# ─── Analytics endpoint ───────────────────────────────────────────────────────

def test_analytics_404():
    client = TestClient(backend.app)
    resp = client.get("/api/sessions/nonexistent-session-id-xyz/analytics")
    assert resp.status_code == 404


def test_analytics_invalid_session_id():
    client = TestClient(backend.app)
    resp = client.get("/api/sessions/../etc/passwd/analytics")
    # Should be 400 or 404, not 500
    assert resp.status_code in (400, 404, 422)
