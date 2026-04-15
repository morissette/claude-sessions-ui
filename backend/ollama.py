"""Ollama helpers for Claude Sessions UI backend."""

import contextlib
import json
import logging
import urllib.error
import urllib.request

from . import constants

logger = logging.getLogger(__name__)

# ─── Ollama helpers ──────────────────────────────────────────────────────────


def ollama_is_available() -> bool:
    try:
        req = urllib.request.Request(f"{constants.OLLAMA_URL}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3):
            return True
    except Exception:
        return False


def ollama_model_pulled(model: str) -> bool:
    try:
        req = urllib.request.Request(f"{constants.OLLAMA_URL}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
        names = [m["name"] for m in data.get("models", [])]
        base = model.split(":")[0]
        return any(base in n for n in names)
    except Exception:
        return False


def ollama_summarize(text: str, model: str | None = None) -> str | None:
    """Call local Ollama to produce a short task title from a raw user message."""
    if model is None:
        model = constants.SUMMARY_MODEL
    prompt = (
        "Summarize this task request in 6-10 words. "
        "Start with a verb. No punctuation at the end. Be specific.\n\n"
        + text[:600]
    )
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode()
    try:
        req = urllib.request.Request(
            f"{constants.OLLAMA_URL}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read()).get("response", "").strip()
            # Strip surrounding quotes if model added them
            return result.strip('"').strip("'")
    except Exception:
        return None


def get_cached_summary(session_id: str) -> str | None:
    p = constants.SUMMARIES_DIR / f"{session_id}.txt"
    try:
        return p.read_text().strip() or None
    except OSError:
        return None


def cache_summary(session_id: str, summary: str) -> None:
    constants.SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)
    (constants.SUMMARIES_DIR / f"{session_id}.txt").write_text(summary)


def compute_truncation_savings() -> dict:
    """Read truncation hook log and aggregate savings per tool."""
    by_tool: dict[str, dict] = {}
    if not constants.TRUNCATION_SAVINGS_FILE.exists():
        return {"tools": {}, "total_tokens_saved": 0, "total_cost_saved_usd": 0.0}
    try:
        for line in constants.TRUNCATION_SAVINGS_FILE.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            tool = e.get("tool", "Unknown")
            if tool not in by_tool:
                by_tool[tool] = {"count": 0, "tokens_saved": 0, "cost_saved_usd": 0.0}
            by_tool[tool]["count"] += 1
            by_tool[tool]["tokens_saved"] += e.get("tokens_saved", 0)
            by_tool[tool]["cost_saved_usd"] = round(
                by_tool[tool]["cost_saved_usd"] + e.get("cost_saved_usd", 0.0), 6
            )
    except OSError:
        pass

    total_tokens = sum(v["tokens_saved"] for v in by_tool.values())
    total_cost = round(sum(v["cost_saved_usd"] for v in by_tool.values()), 4)
    return {
        "tools": by_tool,
        "total_tokens_saved": total_tokens,
        "total_cost_saved_usd": total_cost,
    }


def compute_ollama_savings() -> dict:
    """Read pr_poller savings log + summary cache to compute total saved cost."""
    pr_skips: list[dict] = []
    if constants.SAVINGS_FILE.exists():
        try:
            for line in constants.SAVINGS_FILE.read_text().splitlines():
                line = line.strip()
                if line:
                    with contextlib.suppress(json.JSONDecodeError):
                        pr_skips.append(json.loads(line))
        except OSError:
            pass

    summary_count = len(list(constants.SUMMARIES_DIR.glob("*.txt")))

    pr_skip_count = len(pr_skips)
    pr_saved_usd = sum(float(e.get("saved_usd", 0)) for e in pr_skips)
    summary_saved_usd = summary_count * constants.SUMMARY_COST_ESTIMATE_USD
    total_saved_usd = pr_saved_usd + summary_saved_usd

    return {
        "pr_skips": pr_skip_count,
        "pr_saved_usd": round(pr_saved_usd, 4),
        "summaries_generated": summary_count,
        "summary_saved_usd": round(summary_saved_usd, 6),
        "total_saved_usd": round(total_saved_usd, 4),
        "recent_skips": [
            {"ts": e.get("ts"), "title": e.get("title", ""), "url": e.get("url", "")}
            for e in pr_skips[-5:]  # last 5 for the UI
        ],
    }
