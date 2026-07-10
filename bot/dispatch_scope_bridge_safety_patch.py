from __future__ import annotations

import builtins
import logging
import os
import sys
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.dispatch_scope_bridge_safety")
_MARKER = "20260709at"
_HOOK = "_NIJA_DISPATCH_SCOPE_BRIDGE_SAFETY_HOOK_20260709AT"
_PATCHED = "_nija_dispatch_scope_bridge_safety_20260709at"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _enabled() -> bool:
    return str(os.environ.get("NIJA_ALLOW_DISPATCH_SCOPE_BRIDGE", "false")).strip().lower() in _TRUE


def _patch(module: ModuleType) -> bool:
    original = getattr(module, "_dispatch_scope_only_block", None)
    if not callable(original) or getattr(original, _PATCHED, False):
        return bool(getattr(original, _PATCHED, False))

    @wraps(original)
    def gated(decision: Any) -> bool:
        return bool(original(decision)) if _enabled() else False

    setattr(gated, _PATCHED, True)
    setattr(module, "_dispatch_scope_only_block", gated)
    logger.warning("DISPATCH_SCOPE_BRIDGE_SAFETY_GATED marker=%s enabled=%s", _MARKER, _enabled())
    return True


def _patch_loaded() -> None:
    for name in ("bot.dispatch_scope_bridge_patch", "dispatch_scope_bridge_patch"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            _patch(module)


def install_import_hook() -> None:
    os.environ.setdefault("NIJA_ALLOW_DISPATCH_SCOPE_BRIDGE", "false")
    _patch_loaded()
    if getattr(builtins, _HOOK, False):
        return
    original_import = builtins.__import__

    def importing(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        if "dispatch_scope_bridge_patch" in str(name):
            _patch_loaded()
        return module

    builtins.__import__ = importing
    setattr(builtins, _HOOK, True)


def install() -> None:
    install_import_hook()
