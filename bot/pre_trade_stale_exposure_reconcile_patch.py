from __future__ import annotations

import builtins
import importlib
import logging
import os
import sys
from functools import wraps
from types import ModuleType
from typing import Any, Mapping

logger = logging.getLogger("nija.pre_trade_stale_exposure_reconcile")
_MARKER = "PRE_TRADE_STALE_EXPOSURE_RECONCILE_PATCHED marker=20260707a"
_ATTR = "_nija_pre_trade_stale_exposure_reconcile_20260707a"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(name: str, default: str = "true") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUE


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except Exception:
        return default


def _capital_open_exposure_usd() -> float | None:
    try:
        try:
            ca_mod = importlib.import_module("bot.capital_authority")
        except Exception:
            ca_mod = importlib.import_module("capital_authority")
        ca = ca_mod.get_capital_authority()
        for attr in ("open_exposure_usd", "current_exposure_usd", "total_open_exposure_usd"):
            val = getattr(ca, attr, None)
            if val is not None:
                return max(0.0, _safe_float(val, 0.0))
        snap = None
        for getter_name in ("get_snapshot", "snapshot", "get_capital_snapshot", "get_status"):
            getter = getattr(ca, getter_name, None)
            if callable(getter):
                try:
                    snap = getter()
                    break
                except Exception:
                    pass
        if isinstance(snap, Mapping):
            for key in ("open_exposure_usd", "current_exposure_usd", "total_open_exposure_usd"):
                if key in snap:
                    return max(0.0, _safe_float(snap.get(key), 0.0))
    except Exception:
        pass
    return None


def _open_position_count_hint() -> int | None:
    best: int | None = None
    try:
        for module_name in ("bot.startup_position_sync", "startup_position_sync", "bot.position_tracker", "position_tracker"):
            module = sys.modules.get(module_name)
            if module is None:
                continue
            for attr in ("open_positions", "positions", "_open_positions", "_positions"):
                value = getattr(module, attr, None)
                if isinstance(value, Mapping):
                    count = len(value)
                    best = count if best is None else max(best, count)
    except Exception:
        pass
    return best


def _maybe_reconcile(engine: Any, *, account_id: str, source: str) -> None:
    if not _truthy("NIJA_PRE_TRADE_STALE_EXPOSURE_RECONCILE_ENABLED", "true"):
        return
    try:
        account_key = engine._account_key(account_id) if hasattr(engine, "_account_key") else str(account_id or "default")
        exposure_map = getattr(engine, "_symbol_exposure_usd", {})
        if not isinstance(exposure_map, dict):
            return
        exposures = exposure_map.get(account_key, {})
        if not isinstance(exposures, dict) or not exposures:
            return
        current_total = sum(_safe_float(v, 0.0) for v in exposures.values())
        stale_min = _float_env("NIJA_PRE_TRADE_STALE_EXPOSURE_MIN_USD", 25.0)
        if current_total < stale_min:
            return
        ca_open = _capital_open_exposure_usd()
        if ca_open is None:
            return
        tolerance = max(1.0, _float_env("NIJA_PRE_TRADE_STALE_EXPOSURE_TOLERANCE_USD", 5.0))
        # If CapitalAuthority says open exposure is near zero but the in-memory
        # pre-trade map is still high, clear stale rejected/old exposure so the
        # next order is judged against the live capital snapshot.
        if ca_open <= tolerance and current_total > max(stale_min, tolerance * 4.0):
            removed = dict(exposures)
            exposure_map.pop(account_key, None)
            logger.critical(
                "PRE_TRADE_STALE_EXPOSURE_RECONCILED marker=20260707a account=%s source=%s stale_total=%.2f ca_open_exposure=%.2f symbols=%s action=cleared_pre_trade_map",
                account_key,
                source,
                current_total,
                ca_open,
                sorted(str(k) for k in removed.keys()),
            )
            print(
                f"[NIJA-PRINT] PRE_TRADE_STALE_EXPOSURE_RECONCILED marker=20260707a account={account_key} stale_total={current_total:.2f} ca_open={ca_open:.2f}",
                flush=True,
            )
    except Exception as exc:
        logger.debug("PRE_TRADE_STALE_EXPOSURE_RECONCILE skipped: %s", exc)


def _patch_module(module: ModuleType) -> bool:
    cls = getattr(module, "PreTradeRiskEngine", None)
    if not isinstance(cls, type):
        return False
    original_assess = getattr(cls, "assess", None)
    if not callable(original_assess) or getattr(original_assess, _ATTR, False):
        return bool(getattr(original_assess, _ATTR, False))

    @wraps(original_assess)
    def assess(self: Any, *args: Any, **kwargs: Any):
        account_id = str(kwargs.get("account_id") or "default")
        _maybe_reconcile(self, account_id=account_id, source="assess_precheck")
        return original_assess(self, *args, **kwargs)

    setattr(assess, _ATTR, True)
    setattr(cls, "assess", assess)
    logger.warning("%s module=%s surface=PreTradeRiskEngine.assess", _MARKER, getattr(module, "__name__", "unknown"))
    print("[NIJA-PRINT] PRE_TRADE_STALE_EXPOSURE_RECONCILE_PATCHED marker=20260707a", flush=True)
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name in ("bot.pre_trade_risk_engine", "pre_trade_risk_engine"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_module(module) or patched
    return patched


def install_import_hook() -> None:
    _try_patch_loaded()
    if getattr(builtins, "_NIJA_PRE_TRADE_STALE_EXPOSURE_RECONCILE_HOOK_20260707A", False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            if name.endswith("pre_trade_risk_engine"):
                _try_patch_loaded()
            else:
                _try_patch_loaded()
        except Exception as exc:
            logger.warning("PRE_TRADE_STALE_EXPOSURE_RECONCILE hook failed name=%s error=%s", name, exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_PRE_TRADE_STALE_EXPOSURE_RECONCILE_HOOK_20260707A", True)
    logger.warning("PRE_TRADE_STALE_EXPOSURE_RECONCILE_IMPORT_HOOK marker=20260707a")


def install() -> None:
    install_import_hook()
