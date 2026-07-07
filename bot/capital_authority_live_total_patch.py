from __future__ import annotations

import builtins
import importlib
import logging
import sys
import threading
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.capital_authority_live_total_patch")
_MARKER = "CAPITAL_AUTHORITY_LIVE_TOTAL_PATCHED marker=20260707a"
_PATCHED_ATTR = "_nija_live_total_patch_20260707a"
_HOOK_FLAG = "_NIJA_CAPITAL_AUTHORITY_LIVE_TOTAL_HOOK_20260707A"
_LOCK = threading.Lock()
_ORIGINAL_IMPORT: Optional[Callable[..., Any]] = None
_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return default


def _snapshot_total(ca: Any) -> float:
    snap = getattr(ca, "_last_typed_snapshot", None)
    return _float(getattr(snap, "real_capital", 0.0), 0.0) if snap is not None else 0.0


def _broker_sum(ca: Any) -> float:
    try:
        getter = getattr(ca, "get_real_capital", None)
        if callable(getter):
            return max(0.0, _float(getter(), 0.0))
    except Exception:
        pass
    try:
        balances = getattr(ca, "_broker_balances", {}) or {}
        if isinstance(balances, dict):
            return max(0.0, sum(_float(v, 0.0) for v in balances.values()))
    except Exception:
        pass
    return 0.0


def _last_update_total(ca: Any) -> float:
    return max(0.0, _float(getattr(ca, "_last_updated_total", 0.0), 0.0))


def _patch_module(module: ModuleType) -> bool:
    cls = getattr(module, "CapitalAuthority", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "total_capital", None)
    if getattr(current, _PATCHED_ATTR, False):
        return True

    def _live_total(self: Any) -> float:
        snapshot = _snapshot_total(self)
        broker_total = _broker_sum(self)
        updated_total = _last_update_total(self)
        total = max(snapshot, broker_total, updated_total, 0.0)
        if total > snapshot + 0.01:
            logger.warning(
                "CAPITAL_AUTHORITY_LIVE_TOTAL_SELECTED marker=20260707a snapshot=$%.2f broker_sum=$%.2f updated=$%.2f selected=$%.2f",
                snapshot,
                broker_total,
                updated_total,
                total,
            )
        return total

    prop = property(_live_total)
    setattr(prop.fget, _PATCHED_ATTR, True)  # type: ignore[union-attr]
    setattr(cls, "total_capital", prop)
    logger.warning("%s module=%s", _MARKER, getattr(module, "__name__", "unknown"))
    print("[NIJA-PRINT] CAPITAL_AUTHORITY_LIVE_TOTAL_PATCHED marker=20260707a", flush=True)
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name in ("bot.capital_authority", "capital_authority"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_module(module) or patched
    return patched


def _patch_import_result(module: Any) -> Any:
    try:
        if isinstance(module, ModuleType) and "capital_authority" in str(getattr(module, "__name__", "")):
            _patch_module(module)
        else:
            _try_patch_loaded()
    except Exception as exc:
        logger.debug("CapitalAuthority live-total import check skipped: %s", exc)
    return module


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT, _ORIGINAL_IMPORT_MODULE
    with _LOCK:
        _try_patch_loaded()
        if getattr(builtins, _HOOK_FLAG, False):
            return
        if _ORIGINAL_IMPORT_MODULE is None:
            _ORIGINAL_IMPORT_MODULE = importlib.import_module

            def import_module(name: str, package: str | None = None):
                module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
                return _patch_import_result(module)

            importlib.import_module = import_module  # type: ignore[assignment]
        if _ORIGINAL_IMPORT is None:
            _ORIGINAL_IMPORT = builtins.__import__

            def importing(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
                module = _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)  # type: ignore[misc]
                return _patch_import_result(module)

            builtins.__import__ = importing
        setattr(builtins, _HOOK_FLAG, True)
        logger.warning("CAPITAL_AUTHORITY_LIVE_TOTAL_IMPORT_HOOK_INSTALLED marker=20260707a")


def install() -> None:
    install_import_hook()
