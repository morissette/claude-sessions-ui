"""Backwards-compatibility shim for the backend package.

Tests import from `backend` and use monkeypatch.setattr(backend, "X", ...).
This shim re-exports everything from backend_compat and forwards attribute
mutations to that module so monkeypatches reach the functions that use them.
"""
import contextlib
import importlib
import sys

from backend_compat import *  # noqa: F401, F403

_COMPAT = importlib.import_module("backend_compat")

# Names that belong to the shim itself and must NOT be delegated to _COMPAT.
_SHIM_ATTRS = frozenset({"_COMPAT", "_SHIM_ATTRS", "__name__", "__loader__",
                          "__package__", "__spec__", "__file__", "__builtins__",
                          "__doc__", "__path__", "__class__"})


class _PatchableModule(type(sys.modules[__name__])):
    def __getattribute__(self, name: str):  # type: ignore[override]
        # For shim-internal names use normal lookup
        if name in _SHIM_ATTRS or name.startswith("__"):
            return super().__getattribute__(name)
        # Everything else: always read from the live _COMPAT module so that
        # assignments like `backend_compat._db_conn = <conn>` are visible even
        # after a previous `backend._db_conn = None` stored None in our __dict__.
        compat = super().__getattribute__("_COMPAT")
        try:
            return getattr(compat, name)
        except AttributeError:
            # Fall back to our own __dict__ for names only in this module
            return super().__getattribute__(name)

    def __setattr__(self, name: str, value) -> None:  # type: ignore[override]
        # Forward to compat module so monkeypatches reach global references
        if name not in _SHIM_ATTRS and not name.startswith("__"):
            with contextlib.suppress(Exception):
                setattr(_COMPAT, name, value)
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _PatchableModule
