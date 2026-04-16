"""Miscellaneous ~/.claude stats endpoint for Claude Sessions UI."""

import asyncio
import contextlib
import json
import re
from pathlib import Path

from fastapi import APIRouter

from .. import constants, database

router = APIRouter()

_BASE = constants.CLAUDE_BASE_DIR


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _count_dir(path: Path) -> int:
    """Count files (non-recursive first level only for speed)."""
    if not path.exists() or not path.is_dir():
        return 0
    try:
        return sum(1 for e in path.iterdir() if e.is_file() and not e.is_symlink())
    except PermissionError:
        return 0


def _list_names(path: Path, exts: tuple = (".md", ".json", ".yaml", ".yml", ".sh", ".py", ".txt")) -> list[str]:
    """Return sorted stem names of files in a dir."""
    if not path.exists() or not path.is_dir():
        return []
    try:
        return sorted(
            e.stem for e in path.iterdir()
            if e.is_file() and not e.is_symlink() and e.suffix in exts
        )
    except PermissionError:
        return []


def _read_json(path: Path) -> dict | list | None:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None


def _parse_frontmatter_type(text: str) -> str | None:
    """Extract `type: value` from YAML frontmatter block."""
    m = re.search(r"^---\s*\n(.*?)^---", text, re.DOTALL | re.MULTILINE)
    if not m:
        return None
    block = m.group(1)
    tm = re.search(r"^\s*type\s*:\s*(\S+)", block, re.MULTILINE)
    return tm.group(1).strip('"\'') if tm else None


# ─── Computation ─────────────────────────────────────────────────────────────


def _compute_misc_stats() -> dict:
    # ── Customization ────────────────────────────────────────────────────────

    skills_names = _list_names(_BASE / "skills")
    commands_names = _list_names(_BASE / "commands")
    agents_names = _list_names(_BASE / "agents")
    hooks_names = _list_names(_BASE / "hooks", (".py", ".sh", ".bash", ".zsh", ".js", ".ts"))
    todos_count = _count_dir(_BASE / "todos")

    # Plugins — may not exist; degrade gracefully
    plugins: list[dict] = []
    plugin_file = _BASE / "plugin_analytics.json"
    raw_plugins = _read_json(plugin_file)
    if isinstance(raw_plugins, dict):
        installed = raw_plugins.get("plugins_installed", [])
        if isinstance(installed, list):
            plugins = [
                {
                    "name": p.get("name", ""),
                    "installed_at": p.get("installed_at", ""),
                    "marketplace": p.get("marketplace", ""),
                }
                for p in installed
                if isinstance(p, dict) and p.get("name")
            ]

    # Settings.json — count permissions, env vars, hook events, enabled plugins
    permissions_allow = 0
    permissions_deny = 0
    env_vars_count = 0
    hook_events: list[str] = []
    enabled_plugins: list[str] = []

    settings_raw = _read_json(_BASE / "settings.json")
    if isinstance(settings_raw, dict):
        perms = settings_raw.get("permissions", {})
        if isinstance(perms, dict):
            allow = perms.get("allow", [])
            deny = perms.get("deny", [])
            permissions_allow = len(allow) if isinstance(allow, list) else 0
            permissions_deny = len(deny) if isinstance(deny, list) else 0
        env = settings_raw.get("env", {})
        env_vars_count = len(env) if isinstance(env, dict) else 0
        hooks_cfg = settings_raw.get("hooks", {})
        hook_events = sorted(hooks_cfg.keys()) if isinstance(hooks_cfg, dict) else []
        ep = settings_raw.get("enabledPlugins", [])
        enabled_plugins = list(ep) if isinstance(ep, list) else []

    # ── Knowledge base ────────────────────────────────────────────────────────

    # Session summary coverage
    summary_count = _count_dir(constants.SUMMARIES_DIR)
    total_sessions_db = 0
    try:
        with database.get_db() as conn:
            row = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()
            total_sessions_db = row[0] if row else 0
    except Exception:
        pass
    summary_coverage_pct = (
        round(summary_count / total_sessions_db * 100, 1)
        if total_sessions_db > 0 else 0.0
    )

    # Plans count + total bytes
    plans_dir = _BASE / "plans"
    plans_count = 0
    plans_total_bytes = 0
    if plans_dir.exists() and plans_dir.is_dir():
        try:
            for f in plans_dir.iterdir():
                if f.is_file() and not f.is_symlink():
                    plans_count += 1
                    with contextlib.suppress(OSError):
                        plans_total_bytes += f.stat().st_size
        except PermissionError:
            pass

    # Memory type distribution — scan ~/.claude/memory/ + all projects/*/memory/
    mem_types: dict[str, int] = {"user": 0, "feedback": 0, "project": 0, "reference": 0, "other": 0}
    memory_dirs: list[Path] = [_BASE / "memory"]
    try:
        for proj_dir in constants.CLAUDE_DIR.iterdir():
            m_dir = proj_dir / "memory"
            if m_dir.is_dir() and not m_dir.is_symlink():
                memory_dirs.append(m_dir)
    except (OSError, PermissionError):
        pass

    project_memory_bases = 0
    for m_dir in memory_dirs:
        if not m_dir.exists():
            continue
        if m_dir != _BASE / "memory":
            project_memory_bases += 1
        try:
            for f in m_dir.iterdir():
                if not f.is_file() or f.suffix not in (".md", ".txt") or f.name == "MEMORY.md":
                    continue
                try:
                    text = f.read_text(encoding="utf-8", errors="replace")
                    t = _parse_frontmatter_type(text)
                    if t in mem_types:
                        mem_types[t] += 1
                    elif t:
                        mem_types["other"] += 1
                except OSError:
                    pass
        except PermissionError:
            pass

    # Remove zero-count "other" to keep response clean
    if mem_types["other"] == 0:
        del mem_types["other"]

    return {
        "customization": {
            "skills_count": len(skills_names),
            "skills": skills_names,
            "commands_count": len(commands_names),
            "commands": commands_names,
            "agents_count": len(agents_names),
            "hooks_count": len(hooks_names),
            "hook_names": hooks_names,
            "hook_events_configured": hook_events,
            "plugins": plugins,
            "plugin_count": len(plugins),
            "enabled_plugins": enabled_plugins,
            "permissions_allow_count": permissions_allow,
            "permissions_deny_count": permissions_deny,
            "env_vars_count": env_vars_count,
            "todos_count": todos_count,
        },
        "knowledge": {
            "session_summary_count": summary_count,
            "total_sessions_db": total_sessions_db,
            "summary_coverage_pct": summary_coverage_pct,
            "memory_by_type": mem_types,
            "project_memory_bases": project_memory_bases,
            "plans_count": plans_count,
            "plans_total_bytes": plans_total_bytes,
        },
    }


# ─── Route ───────────────────────────────────────────────────────────────────


@router.get("/api/misc-stats")
async def get_misc_stats():
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _compute_misc_stats)
