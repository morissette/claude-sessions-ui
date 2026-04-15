"""Process discovery helpers for Claude Sessions UI backend."""

import logging

import psutil

logger = logging.getLogger(__name__)


# ─── Process discovery ────────────────────────────────────────────────────────

def get_running_claude_processes() -> dict[int, dict]:
    """Return {pid: {cwd, session_id, create_time}} for all claude processes."""
    result: dict[int, dict] = {}
    for p in psutil.process_iter(["pid", "name", "cmdline", "cwd", "create_time"]):
        try:
            name = p.info["name"] or ""
            cmdline = p.info["cmdline"] or []
            is_claude = name == "claude" or any(
                c.endswith("/claude") or c.endswith("/claude-code") or c == "claude"
                for c in cmdline[:2] if c
            )
            if not is_claude:
                continue
            session_id = None
            for i, arg in enumerate(cmdline):
                if arg == "--resume" and i + 1 < len(cmdline):
                    session_id = cmdline[i + 1]
                    break
            result[p.info["pid"]] = {
                "pid": p.info["pid"],
                "cwd": p.info["cwd"],
                "session_id": session_id,
                "create_time": p.info["create_time"],
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return result
