"""Normalize account identities for Kraken margin exit cost buffers."""

from __future__ import annotations

import builtins
import logging
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.kraken_exit_margin_cost")
_MARKER = "20260713-kraken-exit-margin-cost-v1"
_ORIGINAL_IMPORT = None
_LOCK = threading.RLock()
_PATCHED: set[tuple[str, int]] = set()


def _canonical_account_id(identity: Any) -> str:
    text = str(identity or "").strip().lower().replace("/", ":")
    parts = [part for part in text.split(":") if part]
    if parts:
        if parts[0] == "platform":
            return "platform"
        if parts[0] == "user" and len(parts) >= 2:
            return parts[1]
    if text.startswith("user_"):
        text = text[5:]
    if text.endswith("_kraken"):
        text = text[:-7]
    return text or "platform"


def _patch_exit_runtime(module: ModuleType) -> bool:
    current = getattr(module, "_margin_extra_buffer", None)
    if not callable(current) or getattr(current, "_nija_canonical_margin_cost_v1", False):
        return False

    @wraps(current)
    def margin_extra_buffer(account: str, symbol: str) -> float:
        canonical = _canonical_account_id(account)
        value = float(current(canonical, symbol) or 0.0)
        logger.debug(
            "KRAKEN_MARGIN_EXIT_COST_BUFFER marker=%s supervisor=%s account_id=%s symbol=%s buffer=%.6f",
            _MARKER, account, canonical, symbol, value,
        )
        return value

    margin_extra_buffer._nija_canonical_margin_cost_v1 = True  # type: ignore[attr-defined]
    module._margin_extra_buffer = margin_extra_buffer
    logger.warning("KRAKEN_MARGIN_EXIT_COST_ACCOUNT_PATCHED marker=%s", _MARKER)
    return True


def _patch_module(module: ModuleType) -> bool:
    key = (str(getattr(module, "__name__", "")), id(module))
    if key in _PATCHED:
        return True
    changed = False
    if str(getattr(module, "__name__", "")).endswith("kraken_all_account_exit_runtime_patch"):
        changed = _patch_exit_runtime(module)
    if changed:
        _PATCHED.add(key)
    return changed


def _patch_loaded() -> None:
    for module in tuple(sys.modules.values()):
        if isinstance(module, ModuleType):
            try:
                _patch_module(module)
            except Exception:
                continue


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT
    _patch_loaded()
    with _LOCK:
        if _ORIGINAL_IMPORT is not None:
            return
        _ORIGINAL_IMPORT = builtins.__import__
        local = threading.local()

        def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
            module = _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)  # type: ignore[misc]
            if getattr(local, "active", False):
                return module
            local.active = True
            try:
                _patch_loaded()
            finally:
                local.active = False
            return module

        builtins.__import__ = guarded_import  # type: ignore[assignment]
    _patch_loaded()
    logger.critical("KRAKEN_EXIT_MARGIN_COST_PATCH_INSTALLED marker=%s", _MARKER)


__all__ = ["install_import_hook", "_canonical_account_id", "_patch_exit_runtime"]
