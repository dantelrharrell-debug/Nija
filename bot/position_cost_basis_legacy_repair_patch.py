"""Preserve legitimate legacy NIJA execution cost basis during reconciliation.

Older tracker rows predate the explicit ``cost_basis_verified`` field.  A positive
entry owned by NIJA strategy execution should remain trusted; startup-adopted or
broker-existing rows remain unverified unless Kraken history supplies a price.
"""

from __future__ import annotations

import builtins
import logging
import sys
import threading
from types import ModuleType
from typing import Any, Mapping

logger = logging.getLogger("nija.position_cost_basis_legacy_repair")
_MARKER = "20260713-cost-basis-legacy-v1"
_PATCH_ATTR = "_nija_legacy_verified_cost_basis_v1"
_ORIGINAL_IMPORT = None
_LOCK = threading.RLock()
_PATCHED: set[tuple[str, int]] = set()


def _f(value: Any) -> float:
    try:
        parsed = float(value or 0.0)
        return parsed if parsed == parsed else 0.0
    except Exception:
        return 0.0


def _legacy_execution_verified(position: Any) -> bool:
    if not isinstance(position, Mapping):
        return False
    if position.get("cost_basis_verified") is not None:
        return position.get("cost_basis_verified") is True
    if _f(position.get("entry_price")) <= 0:
        return False
    source = str(position.get("position_source") or "").strip().lower()
    strategy = str(position.get("strategy") or "").strip().upper()
    entry_source = str(position.get("entry_price_source") or "").strip().lower()
    if entry_source in {"execution", "api", "trade_history", "closed_orders", "fills"}:
        return True
    if source in {"nija_strategy", "strategy_execution", "execution"} and strategy not in {"STARTUP_SYNC", "BROKER_SYNC"}:
        return True
    return False


def _patch_class(cls: type) -> bool:
    current = getattr(cls, "_existing_verified", None)
    if not callable(current) or getattr(current, _PATCH_ATTR, False):
        return False
    original = current

    def existing_verified(inner_cls, position):
        try:
            if original(position):
                return True
        except TypeError:
            if original(inner_cls, position):
                return True
        verified = _legacy_execution_verified(position)
        if verified:
            logger.info(
                "LEGACY_EXECUTION_COST_BASIS_PRESERVED marker=%s symbol=%s entry=%s",
                _MARKER,
                position.get("symbol", "unknown") if isinstance(position, Mapping) else "unknown",
                position.get("entry_price") if isinstance(position, Mapping) else None,
            )
        return verified

    setattr(existing_verified, _PATCH_ATTR, True)
    setattr(cls, "_existing_verified", classmethod(existing_verified))
    logger.warning("POSITION_COST_BASIS_LEGACY_REPAIR_PATCHED marker=%s class=%s", _MARKER, cls.__name__)
    return True


def _patch_module(module: ModuleType) -> bool:
    key = (str(getattr(module, "__name__", "")), id(module))
    if key in _PATCHED:
        return True
    cls = getattr(module, "PositionTracker", None)
    changed = _patch_class(cls) if isinstance(cls, type) else False
    if changed:
        _PATCHED.add(key)
    return changed


def _patch_loaded() -> None:
    for name in ("bot.position_tracker", "position_tracker"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            _patch_module(module)


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
            if name.endswith("position_tracker"):
                local.active = True
                try:
                    _patch_loaded()
                finally:
                    local.active = False
            return module

        builtins.__import__ = guarded_import  # type: ignore[assignment]
    _patch_loaded()
    logger.critical("POSITION_COST_BASIS_LEGACY_REPAIR_INSTALLED marker=%s", _MARKER)


__all__ = ["install_import_hook", "_legacy_execution_verified", "_patch_class"]
