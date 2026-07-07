from __future__ import annotations

import builtins
import logging
import os
import sys
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.phase3_sector_headroom_prefilter")

_MARKER = "PHASE3_SECTOR_HEADROOM_PREFILTER_PATCHED marker=20260707a"
_IMPORT_FLAG = "_NIJA_PHASE3_SECTOR_HEADROOM_PREFILTER_IMPORT_HOOK_20260707A"
_WRAP_ATTR = "_nija_phase3_sector_headroom_prefilter_wrapped_20260707a"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(name: str, default: str = "true") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUE


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _symbol_from_signal(signal: Any) -> str:
    if isinstance(signal, dict):
        return str(signal.get("symbol") or signal.get("pair") or "").upper().replace("/", "-")
    return str(getattr(signal, "symbol", None) or getattr(signal, "pair", None) or signal or "").upper().replace("/", "-")


def _capital_value(loop: Any) -> float:
    # Prefer the currently visible CapitalAuthority total; fall back to loop/strategy fields.
    for mod_name in ("bot.capital_authority", "capital_authority"):
        try:
            mod = __import__(mod_name, fromlist=["get_capital_authority"])
            getter = getattr(mod, "get_capital_authority", None)
            if callable(getter):
                ca = getter()
                for attr in ("total_capital", "real_capital", "usable_capital", "get_usable_capital"):
                    value = getattr(ca, attr, None)
                    value = value() if callable(value) else value
                    amount = _float(value, 0.0)
                    if amount > 0:
                        return amount
        except Exception:
            pass
    for obj in (loop, getattr(loop, "strategy", None), getattr(loop, "apex", None)):
        if obj is None:
            continue
        for attr in ("total_capital", "portfolio_value", "capital", "account_value", "balance"):
            amount = _float(getattr(obj, attr, 0.0), 0.0)
            if amount > 0:
                return amount
    return _float(os.environ.get("NIJA_PHASE3_PREFILTER_PORTFOLIO_FALLBACK_USD"), 74.29)


def _position_size(loop: Any, symbol: str) -> float:
    for obj in (loop, getattr(loop, "strategy", None), getattr(loop, "apex", None)):
        if obj is None:
            continue
        for attr in ("position_size", "default_position_size", "trade_size_usd", "min_trade_usd"):
            amount = _float(getattr(obj, attr, 0.0), 0.0)
            if amount > 0:
                return amount
    return _float(os.environ.get("NIJA_PHASE3_PREFILTER_TEST_SIZE_USD"), _float(os.environ.get("MIN_TRADE_USD"), 10.0))


def _portfolio_risk_engine(loop: Any) -> Any | None:
    # Prefer already-hydrated strategy/apex/AI objects.
    for obj in (loop, getattr(loop, "strategy", None), getattr(loop, "apex", None), getattr(loop, "ai_hub", None)):
        if obj is None:
            continue
        for attr in ("portfolio_risk_engine", "risk_engine", "_portfolio_risk_engine"):
            engine = getattr(obj, attr, None)
            if engine is not None and callable(getattr(engine, "check_sector_limits", None)):
                return engine
    try:
        mod = __import__("bot.ai_intelligence_hub", fromlist=["get_ai_hub"])
        getter = getattr(mod, "get_ai_hub", None)
        if callable(getter):
            hub = getter()
            engine = getattr(hub, "portfolio_risk_engine", None)
            if engine is not None and callable(getattr(engine, "check_sector_limits", None)):
                return engine
    except Exception:
        pass
    return None


def _sector_prefilter_blocks(loop: Any, signal: Any) -> tuple[bool, str]:
    if not _truthy("NIJA_PHASE3_SECTOR_HEADROOM_PREFILTER", "true"):
        return False, "disabled"
    symbol = _symbol_from_signal(signal)
    if not symbol:
        return False, "missing_symbol"
    engine = _portfolio_risk_engine(loop)
    if engine is None:
        return False, "risk_engine_unavailable"
    portfolio_value = _capital_value(loop)
    size_usd = _position_size(loop, symbol)
    if portfolio_value <= 0 or size_usd <= 0:
        return False, "missing_capital_or_size"
    try:
        allowed, adjusted_size, info = engine.check_sector_limits(symbol, size_usd, portfolio_value)
    except Exception as exc:
        logger.debug("PHASE3_SECTOR_HEADROOM_PREFILTER_CHECK_SKIPPED symbol=%s err=%s", symbol, exc)
        return False, "check_error"
    if allowed:
        return False, "allowed"
    reason = (
        f"sector_hard_block symbol={symbol} sector={info.get('sector_name') or info.get('sector')} "
        f"projected_pct={_float(info.get('projected_sector_exposure_pct'), 0.0)*100:.1f} "
        f"hard_limit_pct={_float(getattr(engine, 'hard_sector_limit_pct', 0.20), 0.20)*100:.1f} "
        f"portfolio_value=${portfolio_value:.2f} requested_usd=${size_usd:.2f}"
    )
    return True, reason


def _filter_signals(loop: Any, signals: Any) -> Any:
    if not isinstance(signals, list) or not signals:
        return signals
    kept = []
    skipped = 0
    for sig in signals:
        blocked, reason = _sector_prefilter_blocks(loop, sig)
        if blocked:
            skipped += 1
            logger.warning(
                "PHASE3_SECTOR_HEADROOM_PREFILTER_SKIP marker=20260707a reason=%s",
                reason,
            )
            print(
                f"[NIJA-PRINT] PHASE3_SECTOR_HEADROOM_PREFILTER_SKIP marker=20260707a {reason}",
                flush=True,
            )
            continue
        kept.append(sig)
    if skipped:
        logger.warning(
            "PHASE3_SECTOR_HEADROOM_PREFILTER_SUMMARY marker=20260707a input=%d kept=%d skipped=%d",
            len(signals),
            len(kept),
            skipped,
        )
    return kept


def _patch_core_loop_module(module: ModuleType) -> bool:
    cls = getattr(module, "NijaCoreLoop", None)
    if not isinstance(cls, type):
        return False
    patched = False

    for method_name in ("_phase3_scan_and_enter",):
        original = getattr(cls, method_name, None)
        if callable(original) and not getattr(original, _WRAP_ATTR, False):
            @wraps(original)
            def wrapper(self: Any, signals: Any = None, *args: Any, __original=original, **kwargs: Any):
                if signals is not None:
                    signals = _filter_signals(self, signals)
                    if isinstance(signals, list) and not signals:
                        logger.warning("PHASE3_SECTOR_HEADROOM_PREFILTER_ALL_SKIPPED marker=20260707a method=%s", method_name)
                return __original(self, signals, *args, **kwargs)

            setattr(wrapper, _WRAP_ATTR, True)
            setattr(cls, method_name, wrapper)
            patched = True

    if patched:
        logger.warning("%s class=bot.nija_core_loop.NijaCoreLoop", _MARKER)
        print("[NIJA-PRINT] PHASE3_SECTOR_HEADROOM_PREFILTER_PATCHED marker=20260707a", flush=True)
    return patched


def _try_patch_loaded() -> bool:
    patched = False
    for name in ("bot.nija_core_loop", "nija_core_loop"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_core_loop_module(module) or patched
    return patched


def install_import_hook() -> None:
    os.environ.setdefault("NIJA_PHASE3_SECTOR_HEADROOM_PREFILTER", "true")
    os.environ.setdefault("NIJA_PHASE3_PREFILTER_TEST_SIZE_USD", os.environ.get("MIN_TRADE_USD", "10"))
    _try_patch_loaded()
    if getattr(builtins, _IMPORT_FLAG, False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            if name.endswith("nija_core_loop") or "nija_core_loop" in str(name):
                _try_patch_loaded()
        except Exception as exc:
            logger.warning("PHASE3_SECTOR_HEADROOM_PREFILTER_IMPORT_FAILED marker=20260707a name=%s err=%s", name, exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, _IMPORT_FLAG, True)
    logger.warning("PHASE3_SECTOR_HEADROOM_PREFILTER_IMPORT_HOOK marker=20260707a installed=true")


def install() -> None:
    install_import_hook()
