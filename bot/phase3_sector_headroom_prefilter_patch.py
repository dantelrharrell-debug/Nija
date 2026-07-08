from __future__ import annotations

import builtins
import logging
import os
import sys
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.phase3_sector_headroom_prefilter")

_MARKER = "PHASE3_SECTOR_HEADROOM_PREFILTER_PATCHED marker=20260707b signature_safe=true"
_IMPORT_FLAG = "_NIJA_PHASE3_SECTOR_HEADROOM_PREFILTER_IMPORT_HOOK_20260707B"
_WRAP_ATTR = "_nija_phase3_sector_headroom_prefilter_wrapped_20260707b"
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

    # Comprehensive sector exposure diagnostics (Fix: sector headroom math).
    _sector_name = info.get("sector_name") or info.get("sector") or "unknown"
    _hard_limit_pct = _float(getattr(engine, "hard_sector_limit_pct", 0.20), 0.20)
    _current_exp_usd = _float(info.get("current_sector_exposure_usd") or info.get("sector_exposure_usd"), 0.0)
    _current_exp_pct = _float(info.get("current_sector_exposure_pct") or info.get("sector_exposure_pct"), 0.0)
    _projected_exp_usd = _float(info.get("projected_sector_exposure_usd"), _current_exp_usd + size_usd)
    _projected_exp_pct = _float(info.get("projected_sector_exposure_pct"), 0.0)
    if _projected_exp_pct == 0.0 and portfolio_value > 0:
        _projected_exp_pct = _projected_exp_usd / portfolio_value
    _headroom_usd = max(0.0, portfolio_value * _hard_limit_pct - _current_exp_usd)
    _existing_positions = info.get("existing_positions_in_sector") or info.get("positions_in_sector") or []

    # Log full sector block detail for observability.
    logger.critical(
        "SECTOR_EXPOSURE_LIMIT_EXCEEDED marker=20260707b "
        "symbol=%s broker=%s sector=%s "
        "current_sector_exposure_usd=%.2f current_sector_exposure_pct=%.1f%% "
        "proposed_position_usd=%.2f "
        "projected_sector_exposure_usd=%.2f projected_sector_exposure_pct=%.1f%% "
        "hard_sector_limit_pct=%.1f%% sector_headroom_usd=%.2f "
        "existing_positions_in_sector=%s total_equity_base=%.2f",
        symbol,
        getattr(loop, "_broker_name", None) or getattr(loop, "broker_name", None) or "unknown",
        _sector_name,
        _current_exp_usd,
        _current_exp_pct * 100,
        size_usd,
        _projected_exp_usd,
        _projected_exp_pct * 100,
        _hard_limit_pct * 100,
        _headroom_usd,
        _existing_positions,
        portfolio_value,
    )
    print(
        f"[NIJA-PRINT] SECTOR_EXPOSURE_LIMIT_EXCEEDED marker=20260707b "
        f"symbol={symbol} sector={_sector_name} "
        f"current_pct={_current_exp_pct*100:.1f}% proposed_usd={size_usd:.2f} "
        f"projected_pct={_projected_exp_pct*100:.1f}% hard_limit_pct={_hard_limit_pct*100:.1f}% "
        f"headroom_usd={_headroom_usd:.2f} equity={portfolio_value:.2f}",
        flush=True,
    )

    reason = (
        f"SECTOR_EXPOSURE_LIMIT_EXCEEDED symbol={symbol} sector={_sector_name} "
        f"current_sector_exposure_pct={_current_exp_pct*100:.1f}% "
        f"projected_sector_exposure_pct={_projected_exp_pct*100:.1f}% "
        f"hard_sector_limit_pct={_hard_limit_pct*100:.1f}% "
        f"sector_headroom_usd={_headroom_usd:.2f} "
        f"proposed_usd={size_usd:.2f} equity={portfolio_value:.2f}"
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
                "PHASE3_SECTOR_HEADROOM_PREFILTER_SKIP marker=20260707b reason=%s",
                reason,
            )
            print(
                f"[NIJA-PRINT] PHASE3_SECTOR_HEADROOM_PREFILTER_SKIP marker=20260707b {reason}",
                flush=True,
            )
            # Record rejection in the core loop's reject_reason_counts so that
            # ORDER_ADMISSION_SUMMARY shows the real top_reject.
            try:
                _record_reject = getattr(loop, "_record_reject", None)
                if callable(_record_reject):
                    _reject_key = (
                        "SECTOR_EXPOSURE_LIMIT_EXCEEDED"
                        if "sector_exposure_limit_exceeded" in reason.lower() or "sector" in reason.lower()
                        else "ENTRY_BLOCKED_TERMINAL_RISK_HARD_BLOCK"
                    )
                    _record_reject(_reject_key)
            except Exception:
                pass
            continue
        kept.append(sig)
    if skipped:
        logger.warning(
            "PHASE3_SECTOR_HEADROOM_PREFILTER_SUMMARY marker=20260707b input=%d kept=%d skipped=%d",
            len(signals),
            len(kept),
            skipped,
        )
    return kept


def _looks_like_signal_list(value: Any) -> bool:
    """Return True only for ranked signal objects, never for symbol lists.

    ``NijaCoreLoop._phase3_scan_and_enter`` has the canonical signature
    ``(broker, snapshot, symbols, available_slots, ...)``.  The prior patch used
    ``signals=None`` as the first wrapper argument and always forwarded it as a
    positional value.  When the core loop called ``broker=...`` by keyword, that
    injected positional ``None`` became a duplicate broker argument and crashed
    the live loop.  This predicate keeps the sector prefilter on true signal
    lists only and leaves broker/snapshot/symbol calls untouched.
    """
    if not isinstance(value, list) or not value:
        return False
    # A list[str] at this layer is a symbol universe, not signal objects.
    if all(isinstance(item, str) for item in value):
        return False
    for item in value:
        if isinstance(item, dict) and ("symbol" in item or "pair" in item):
            return True
        if hasattr(item, "symbol") or hasattr(item, "pair"):
            return True
    return False


def _patch_core_loop_module(module: ModuleType) -> bool:
    cls = getattr(module, "NijaCoreLoop", None)
    if not isinstance(cls, type):
        return False
    patched = False

    for method_name in ("_phase3_scan_and_enter",):
        original = getattr(cls, method_name, None)
        if callable(original) and not getattr(original, _WRAP_ATTR, False):
            @wraps(original)
            def wrapper(self: Any, *args: Any, __original=original, __method_name=method_name, **kwargs: Any):
                try:
                    # Keyword legacy path: filter only an explicit signal list.
                    if _looks_like_signal_list(kwargs.get("signals")):
                        filtered = _filter_signals(self, kwargs.get("signals"))
                        kwargs = dict(kwargs)
                        kwargs["signals"] = filtered
                        if isinstance(filtered, list) and not filtered:
                            logger.warning(
                                "PHASE3_SECTOR_HEADROOM_PREFILTER_ALL_SKIPPED marker=20260707b method=%s source=kwargs",
                                __method_name,
                            )
                    # Positional legacy path: filter only if the first positional
                    # argument is a signal list.  Do not touch broker/snapshot/
                    # symbols calls.
                    elif args and _looks_like_signal_list(args[0]):
                        filtered = _filter_signals(self, args[0])
                        args = (filtered, *args[1:])
                        if isinstance(filtered, list) and not filtered:
                            logger.warning(
                                "PHASE3_SECTOR_HEADROOM_PREFILTER_ALL_SKIPPED marker=20260707b method=%s source=args",
                                __method_name,
                            )
                except Exception as exc:
                    logger.warning(
                        "PHASE3_SECTOR_HEADROOM_PREFILTER_SIGNATURE_SAFE_SKIP marker=20260707b method=%s err=%s",
                        __method_name,
                        exc,
                    )
                return __original(self, *args, **kwargs)

            setattr(wrapper, _WRAP_ATTR, True)
            setattr(cls, method_name, wrapper)
            patched = True

    if patched:
        logger.warning("%s class=bot.nija_core_loop.NijaCoreLoop", _MARKER)
        print("[NIJA-PRINT] PHASE3_SECTOR_HEADROOM_PREFILTER_PATCHED marker=20260707b signature_safe=true", flush=True)
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
            logger.warning("PHASE3_SECTOR_HEADROOM_PREFILTER_IMPORT_FAILED marker=20260707b name=%s err=%s", name, exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, _IMPORT_FLAG, True)
    logger.warning("PHASE3_SECTOR_HEADROOM_PREFILTER_IMPORT_HOOK marker=20260707b installed=true")


def install() -> None:
    install_import_hook()
