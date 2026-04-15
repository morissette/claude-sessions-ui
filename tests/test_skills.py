"""Tests for backend.skills — skill export, slugify, template generation."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

import backend

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
        jsonl.write_text("\n".join(json.dumps(row) for row in lines) + "\n")
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
        jsonl.write_text("\n".join(json.dumps(row) for row in lines) + "\n")
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
