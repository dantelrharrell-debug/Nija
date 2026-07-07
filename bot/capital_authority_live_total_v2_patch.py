from __future__ import annotations

import builtins
import importlib
import logging
import sys
import threading
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.capital_authority_live_total_v2_patch")
_MARKER = "CAPITAL_AUTHORITY_LIVE_TOTAL_PATCHED marker=20260707b"
_PATCHED_ATTR = "_nija_live_total_patch_20260707b"
_HOOK_FLAG = "_NIJA_CAPITAL_AUTHORITY_LIVE_TOTAL_HOOK_20260707B"
_LOCK = threading.Lock()
_ORIGINAL_IMPORT: Optional[Callable[..., Any]] = None
_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_APPLIED = False


def _num(value: Any) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except Exception:
        return 0.0


def _read_totals(ca: Any) -> tuple[float, float, float]:
    snap = getattr(ca, "_last_typed_snapshot", None)
    snapshot = _num(getattr(snap, "real_capital", 0.0)) if snap is not None else 0.0
    updated = _num(getattr(ca, "_last_updated_total", 0.0))
    broker_total = 0.0
    getter = getattr(ca, "get_real_capital", None)
    if callable(getter):
        try:
            broker_total = _num(getter())
        except Exception:
            broker_total = 0.0
    if broker_total <= 0.0:
        balances = getattr(ca, "_broker_balances", {}) or {}
        if isinstance(balances, dict):
            broker_total = _num(sum(_num(v) for v in balances.values()))
    return snapshot, broker_total, updated


def _patch_module(module: ModuleType) -> bool:
    global _APPLIED
    cls = getattr(module, "CapitalAuthority", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "total_capital", None)
    if getattr(getattr(current, "fget", current), _PATCHED_ATTR, False):
        _APPLIED = True
        return True

    def live_total(self: Any) -> float:
        snapshot, broker_total, updated = _read_totals(self)
        selected = max(snapshot, broker_total, updated)
        if selected > snapshot + 0.01:
            logger.warning(
                "CAPITAL_AUTHORITY_LIVE_TOTAL_SELECTED marker=20260707b snapshot=$%.2f broker_sum=$%.2f updated=$%.2f selected=$%.2f",
                snapshot,
                broker_total,
                updated,
                selected,
            )
        return selected

    setattr(live_total, _PATCHED_ATTR, True)
    setattr(cls, "total_capital", property(live_total))
    _APPLIED = True
    logger.warning("%s module=%s", _MARKER, getattr(module, "__name__", "unknown"))
    print("[NIJA-PRINT] CAPITAL_AUTHORITY_LIVE_TOTAL_PATCHED marker=20260707b", flush=True)
    return True


def _try_patch_loaded() -> bool:
    if _APPLIED:
        return True
    patched = False
    for name in ("bot.capital_authority", "capital_authority"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_module(module) or patched
    return patched


def _patch_result(module: Any) -> Any:
    if not _APPLIED:
        try:
            if isinstance(module, ModuleType) and "capital_authority" in str(getattr(module, "__name__", "")):
                _patch_module(module)
            else:
                _try_patch_loaded()
        except Exception as exc:
            logger.debug("live total patch skipped: %s", exc)
    return module


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT, _ORIGINAL_IMPORT_MODULE
    with _LOCK:
        _try_patch_loaded()
        if getattr(builtins, _HOOK_FLAG, False):
            return
        _ORIGINAL_IMPORT_MODULE = importlib.import_module

        def import_module(name: str, package: str | None = None):
            return _patch_result(_ORIGINAL_IMPORT_MODULE(name, package))  # type: ignore[misc]

        importlib.import_module = import_module  # type: ignore[assignment]
        _ORIGINAL_IMPORT = builtins.__import__

        def py_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
            return _patch_result(_ORIGINAL_IMPORT(name, globals, locals, fromlist, level))  # type: ignore[misc]

        builtins.__import__ = py_import
        setattr(builtins, _HOOK_FLAG, True)
        logger.warning("CAPITAL_AUTHORITY_LIVE_TOTAL_IMPORT_HOOK_INSTALLED marker=20260707b")


def install() -> None:
    install_import_hook()
