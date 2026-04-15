"""Prometheus metrics for Claude Sessions UI backend."""

from prometheus_client import (
    CONTENT_TYPE_LATEST,  # noqa: F401 — re-exported for callers
    generate_latest,  # noqa: F401 — re-exported for callers
)

# Import the gauge objects from backend_compat so we never double-register them.
# backend_compat owns the Gauge definitions; this module provides _update_prometheus.
from backend_compat import (
    cost_today,
    cost_total,
    sessions_active,
    sessions_total,
    subagents_total,
    tokens_cache_create,
    tokens_cache_read,
    tokens_input,
    tokens_output,
    turns_total,
)

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
