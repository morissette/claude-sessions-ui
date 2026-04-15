"""Backend package for Claude Sessions UI.

Exports all public symbols via lazy submodule lookup so that:
  - `import backend; backend.SYMBOL` works for any exported name
  - `monkeypatch.setattr(backend, "SYMBOL", value)` patches the real submodule
"""
import importlib
import sys

# Maps every symbol tests/app use → (submodule, attribute_name)
_SUBMODULE_MAP: dict[str, tuple[str, str]] = {
    # constants
    "CLAUDE_DIR": ("constants", "CLAUDE_DIR"),
    "DB_PATH": ("constants", "DB_PATH"),
    "SUMMARIES_DIR": ("constants", "SUMMARIES_DIR"),
    "SAVINGS_FILE": ("constants", "SAVINGS_FILE"),
    "TRUNCATION_SAVINGS_FILE": ("constants", "TRUNCATION_SAVINGS_FILE"),
    "SKILLS_DIR": ("constants", "SKILLS_DIR"),
    "CONFIG_PATH": ("constants", "CONFIG_PATH"),
    "MODEL_PRICING": ("constants", "MODEL_PRICING"),
    "TIME_RANGE_HOURS": ("constants", "TIME_RANGE_HOURS"),
    "CLAUDE_BASE_DIR": ("constants", "CLAUDE_BASE_DIR"),
    "OLLAMA_URL": ("constants", "OLLAMA_URL"),
    "SUMMARY_MODEL": ("constants", "SUMMARY_MODEL"),
    "LIVE_HOURS": ("constants", "LIVE_HOURS"),
    # parsing
    "_session_cache": ("parsing", "_session_cache"),
    "_cwd_cache": ("parsing", "_cwd_cache"),
    "parse_session_file": ("parsing", "parse_session_file"),
    "get_session_cwd": ("parsing", "get_session_cwd"),
    # database
    "_db_conn": ("database", "_db_conn"),
    "init_db": ("database", "init_db"),
    "upsert_sessions_to_db": ("database", "upsert_sessions_to_db"),
    "get_sessions_from_db": ("database", "get_sessions_from_db"),
    "get_session_by_id": ("database", "get_session_by_id"),
    # config
    "_config_cache": ("config", "_config_cache"),
    "_read_config_from_disk": ("config", "_read_config_from_disk"),
    "read_config": ("config", "read_config"),
    "write_config": ("config", "write_config"),
    "check_budget_status": ("config", "check_budget_status"),
    "validate_flag_path": ("config", "validate_flag_path"),
    # aggregation
    "compute_global_stats": ("aggregation", "compute_global_stats"),
    "compute_project_stats": ("aggregation", "compute_project_stats"),
    "get_all_sessions": ("aggregation", "get_all_sessions"),
    "get_sessions_for_range": ("aggregation", "get_sessions_for_range"),
    # detail
    "_analytics_cache": ("detail", "_analytics_cache"),
    "find_session_file": ("detail", "find_session_file"),
    "parse_session_detail": ("detail", "parse_session_detail"),
    # skills
    "slugify_skill_name": ("skills", "slugify_skill_name"),
    "extract_session_skill_data": ("skills", "extract_session_skill_data"),
    "resolve_skill_path": ("skills", "resolve_skill_path"),
    "template_generate_skill": ("skills", "template_generate_skill"),
    # ollama
    "compute_truncation_savings": ("ollama", "compute_truncation_savings"),
    "compute_ollama_savings": ("ollama", "compute_ollama_savings"),
    "get_cached_summary": ("ollama", "get_cached_summary"),
    "cache_summary": ("ollama", "cache_summary"),
    "ollama_is_available": ("ollama", "ollama_is_available"),
    # memory
    "validate_memory_path": ("memory", "validate_memory_path"),
    # process
    "get_running_claude_processes": ("process", "get_running_claude_processes"),
    # app
    "app": ("app", "app"),
}


def __getattr__(name: str):
    if name in _SUBMODULE_MAP:
        mod_name, attr = _SUBMODULE_MAP[name]
        return getattr(importlib.import_module(f"backend.{mod_name}"), attr)
    raise AttributeError(f"module 'backend' has no attribute {name!r}")


class _PatchableModule(type(sys.modules[__name__])):
    """Module subclass that delegates mapped names to their real submodules.

    Python automatically stores submodule references on the parent package
    (e.g. ``backend.app`` becomes the ``backend.app`` module), which would
    shadow our symbol mappings if we only used ``__getattr__``.  Overriding
    ``__getattribute__`` ensures that names in ``_SUBMODULE_MAP`` always
    resolve to their declared submodule attribute, even after Python has
    cached the submodule reference in the package's ``__dict__``.

    ``__setattr__`` forwards assignments to the owning submodule so that
    ``monkeypatch.setattr(backend, "X", value)`` patches the real global.
    """

    def __getattribute__(self, name: str):  # type: ignore[override]
        # Avoid infinite recursion for our own internals
        if name.startswith("__") or name in ("_SUBMODULE_MAP",):
            return super().__getattribute__(name)
        submap = super().__getattribute__("_SUBMODULE_MAP")
        if name in submap:
            mod_name, attr = submap[name]
            return getattr(importlib.import_module(f"backend.{mod_name}"), attr)
        return super().__getattribute__(name)

    def __setattr__(self, name: str, value) -> None:  # type: ignore[override]
        if name in _SUBMODULE_MAP:
            mod_name, attr = _SUBMODULE_MAP[name]
            mod = importlib.import_module(f"backend.{mod_name}")
            # If Python's import machinery is registering the submodule on the
            # parent package (e.g. backend.app = <module backend.app>), let it
            # store normally — don't redirect to mod.app = mod (which would
            # corrupt the FastAPI instance stored in backend/app.py).
            if value is mod and attr == mod_name:
                super().__setattr__(name, value)
                return
            setattr(mod, attr, value)
            return
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _PatchableModule
