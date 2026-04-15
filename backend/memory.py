"""Memory Explorer helpers for Claude Sessions UI backend."""

from pathlib import Path

from fastapi import HTTPException

from . import constants

# ─── Memory Explorer helpers ─────────────────────────────────────────────────


def validate_memory_path(rel_path: str) -> Path:
    """Resolve rel_path relative to CLAUDE_BASE_DIR. Raises HTTPException 403 if unsafe.

    Security: rejects null bytes, paths outside CLAUDE_BASE_DIR, paths outside the
    specific allowed subdirectory (prevents traversal like 'memory/../secrets.db'),
    and paths whose root component is not in the allowlist.
    """
    if "\x00" in rel_path:
        raise HTTPException(status_code=403, detail="Invalid path")

    parts = Path(rel_path).parts
    if not parts:
        raise HTTPException(status_code=403, detail="Empty path")

    root = parts[0]
    if root not in constants.MEMORY_ALLOWLIST and rel_path not in constants.MEMORY_ALLOWLIST_FILES:
        raise HTTPException(status_code=403, detail="Directory not allowed")

    try:
        resolved = (constants.CLAUDE_BASE_DIR / rel_path).resolve()
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=403, detail="Invalid path") from exc

    # For top-level allowlisted files (e.g. "settings.json"), verify they stay within
    # CLAUDE_BASE_DIR.  For directory-rooted paths (e.g. "memory/…"), verify the
    # resolved path stays strictly inside that specific subdirectory so that a path
    # like "memory/../claude-sessions-ui.db" is rejected even though its parts[0] is
    # "memory" and the resolved target would still be inside CLAUDE_BASE_DIR.
    if rel_path in constants.MEMORY_ALLOWLIST_FILES:
        allowed_base = constants.CLAUDE_BASE_DIR.resolve()
    else:
        allowed_base = (constants.CLAUDE_BASE_DIR / root).resolve()

    if resolved != allowed_base and not resolved.is_relative_to(allowed_base):
        raise HTTPException(status_code=403, detail="Path traversal detected")

    return resolved
