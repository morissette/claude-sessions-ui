"""Memory Explorer HTTP endpoints."""

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException

from backend import constants
from backend import memory as memory_module

router = APIRouter()


@router.get("/api/memory")
async def get_memory_tree():
    def _build_tree() -> dict:
        base = constants.CLAUDE_BASE_DIR.resolve()
        tree: dict = {"type": "dir", "name": ".claude", "children": []}

        for fname in constants.MEMORY_ALLOWLIST_FILES:
            fp = base / fname
            if fp.exists() and fp.is_file() and not fp.is_symlink():
                try:
                    stat = fp.stat()
                    tree["children"].append({
                        "type": "file",
                        "name": fname,
                        "path": fname,
                        "size": stat.st_size,
                        "mtime": stat.st_mtime,
                    })
                except OSError:
                    pass

        for dname in constants.MEMORY_ALLOWLIST:
            dp = base / dname
            if dp.exists() and dp.is_dir() and not dp.is_symlink():
                tree["children"].append(_build_dir(dp, dname))

        return tree

    def _build_dir(directory: Path, rel_prefix: str) -> dict:
        children = []
        try:
            for entry in sorted(directory.iterdir(), key=lambda e: e.name):
                if entry.is_symlink():
                    continue
                rel = f"{rel_prefix}/{entry.name}"
                if entry.is_file():
                    try:
                        stat = entry.stat()
                        children.append({
                            "type": "file",
                            "name": entry.name,
                            "path": rel,
                            "size": stat.st_size,
                            "mtime": stat.st_mtime,
                        })
                    except OSError:
                        pass
                elif entry.is_dir() and not entry.name.startswith("."):
                    children.append(_build_dir(entry, rel))
        except PermissionError:
            pass
        return {"type": "dir", "name": directory.name, "path": rel_prefix, "children": children}

    result = await asyncio.get_running_loop().run_in_executor(None, _build_tree)
    return result


@router.get("/api/memory/file")
async def get_memory_file(path: str):
    resolved = memory_module.validate_memory_path(path)

    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    MAX_SIZE = 500 * 1024
    try:
        stat = resolved.stat()
    except OSError as exc:
        raise HTTPException(status_code=404, detail="File not found") from exc

    truncated = stat.st_size > MAX_SIZE

    try:
        content = resolved.read_bytes()[:MAX_SIZE].decode("utf-8", errors="replace")
    except OSError as exc:
        raise HTTPException(status_code=404, detail="Cannot read file") from exc

    suffix = resolved.suffix.lower()
    if suffix in (".md", ".markdown"):
        mime = "text/markdown"
    elif suffix == ".json":
        mime = "application/json"
    else:
        mime = "text/plain"

    return {
        "path": path,
        "name": resolved.name,
        "content": content,
        "mime": mime,
        "size": stat.st_size,
        "mtime": stat.st_mtime,
        "truncated": truncated,
    }
