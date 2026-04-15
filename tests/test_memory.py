"""Tests for backend.memory — validate_memory_path path traversal guards."""

import pathlib

import pytest
from fastapi import HTTPException

import backend

# ─── TestValidateMemoryPath ───────────────────────────────────────────────────

class TestValidateMemoryPath:
    def test_valid_path(self):
        # Should not raise
        result = backend.validate_memory_path("memory/test.md")
        assert isinstance(result, pathlib.Path)

    def test_dotdot_traversal(self):
        with pytest.raises(HTTPException) as exc_info:
            backend.validate_memory_path("memory/../../etc/passwd")
        assert exc_info.value.status_code == 403

    def test_null_byte_injection(self):
        with pytest.raises(HTTPException) as exc_info:
            backend.validate_memory_path("memory/\x00evil")
        assert exc_info.value.status_code == 403

    def test_non_allowlisted_directory(self):
        with pytest.raises(HTTPException) as exc_info:
            backend.validate_memory_path("random_dir/file.txt")
        assert exc_info.value.status_code == 403

    def test_traversal_within_claude_dir(self):
        """'memory/../claude-sessions-ui.db' has parts[0]=='memory' but resolves outside
        the memory/ subtree — must be rejected even though it stays inside ~/.claude."""
        with pytest.raises(HTTPException) as exc_info:
            backend.validate_memory_path("memory/../claude-sessions-ui.db")
        assert exc_info.value.status_code == 403
