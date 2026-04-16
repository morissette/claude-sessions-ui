"""Shared pytest configuration for the test suite."""

from __future__ import annotations

from pathlib import Path

import pytest


# ─── Shared JSONL fixture data ────────────────────────────────────────────────


@pytest.fixture(scope="session")
def claude_fixture_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate realistic Claude session JSONL files in a temp directory.

    Returns the projects root (equivalent to ``~/.claude/projects`` on a real
    install) containing 6 sessions across 3 projects with varied models, turn
    counts, tool use, thinking blocks, subagent metadata, and a summary block.

    All timestamps are relative to "now", so sessions are always visible in
    the 1h and 1d UI time-range views.

    Usage in a test::

        def test_something(claude_fixture_dir, monkeypatch):
            monkeypatch.setattr(backend, "CLAUDE_DIR", claude_fixture_dir)
            ...
    """
    from fixtures.generate import generate  # local import keeps startup fast

    output_root = tmp_path_factory.mktemp("claude_fixture")
    return generate(output_root)
