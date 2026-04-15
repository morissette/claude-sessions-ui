"""Prometheus metrics for Claude Sessions UI backend."""

from prometheus_client import (
    CONTENT_TYPE_LATEST,  # noqa: F401 — re-exported for callers
    Gauge,
    generate_latest,  # noqa: F401 — re-exported for callers
)

# ─── Gauge definitions ────────────────────────────────────────────────────────

sessions_total = Gauge("claude_sessions_total", "Total Claude sessions scanned")
sessions_active = Gauge("claude_sessions_active", "Currently active Claude sessions")
tokens_input = Gauge("claude_tokens_input_total", "Total input tokens across all sessions")
tokens_output = Gauge("claude_tokens_output_total", "Total output tokens across all sessions")
tokens_cache_create = Gauge("claude_tokens_cache_create_total", "Total cache-creation tokens")
tokens_cache_read = Gauge("claude_tokens_cache_read_total", "Total cache-read tokens")
cost_total = Gauge("claude_cost_usd_total", "Estimated total cost USD across all sessions")
cost_today = Gauge("claude_cost_usd_today", "Estimated cost USD for today")
turns_total = Gauge("claude_turns_total", "Total conversation turns across all sessions")
subagents_total = Gauge("claude_subagents_total", "Total subagents spawned across all sessions")

# ─── Prometheus metrics ───────────────────────────────────────────────────────

def _update_prometheus(stats: dict) -> None:
    sessions_total.set(stats["total_sessions"])
    sessions_active.set(stats["active_sessions"])
    tokens_input.set(stats["total_input_tokens"])
    tokens_output.set(stats["total_output_tokens"])
    tokens_cache_create.set(stats["total_cache_create_tokens"])
    tokens_cache_read.set(stats["total_cache_read_tokens"])
    cost_total.set(stats["total_cost_usd"])
    cost_today.set(stats["cost_today_usd"])
    turns_total.set(stats["total_turns"])
    subagents_total.set(stats["total_subagents"])
