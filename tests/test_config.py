"""Tests for backend.config — config read/write, budget status, flag path validation."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import backend

# ─── Config read/write ────────────────────────────────────────────────────────

def test_read_config_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, "CONFIG_PATH", tmp_path / "nonexistent.json")
    monkeypatch.setattr(backend, "_config_cache", None)
    cfg = backend._read_config_from_disk()
    assert cfg == {"daily_budget_usd": None, "weekly_budget_usd": None}


def test_put_config_ignores_unknown_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(backend, "_config_cache", None)
    with TestClient(backend.app) as client:
        resp = client.put("/api/config", json={"daily_budget_usd": 5.0, "unknown_key": "ignored"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["daily_budget_usd"] == 5.0
        assert "unknown_key" not in data


# ─── Budget status ────────────────────────────────────────────────────────────

def test_check_budget_status_no_budgets():
    result = backend.check_budget_status({"cost_today_usd": 5.0, "cost_week_usd": 20.0}, {})
    assert result["daily"] is None
    assert result["weekly"] is None


def test_check_budget_status_daily_under():
    result = backend.check_budget_status({"cost_today_usd": 5.0, "cost_week_usd": 0.0}, {"daily_budget_usd": 10.0})
    assert result["daily"]["exceeded"] is False
    assert result["daily"]["pct"] == 50.0


def test_check_budget_status_daily_exceeded():
    result = backend.check_budget_status({"cost_today_usd": 12.0, "cost_week_usd": 0.0}, {"daily_budget_usd": 10.0})
    assert result["daily"]["exceeded"] is True
    assert result["daily"]["pct"] == 120.0


def test_check_budget_status_weekly():
    result = backend.check_budget_status({"cost_today_usd": 0.0, "cost_week_usd": 55.0}, {"weekly_budget_usd": 50.0})
    assert result["weekly"]["exceeded"] is True


# ─── Flag path validation ─────────────────────────────────────────────────────

def test_validate_flag_path_outside_claude_dir():
    with pytest.raises(ValueError):
        backend.validate_flag_path("/etc/evil")


def test_validate_flag_path_none_for_empty():
    assert backend.validate_flag_path("") is None


def test_validate_flag_path_rejects_prefix_bypass(tmp_path):
    """~/.claude_evil/ must be rejected — startswith prefix bypass"""
    # Construct a path that starts with ~/.claude text but is a sibling dir
    home = Path.home()
    evil_path = str(home / ".claude_evil" / "budget-exceeded.flag")
    with pytest.raises(ValueError):
        backend.validate_flag_path(evil_path)
