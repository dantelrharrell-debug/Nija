from __future__ import annotations

import builtins
import logging
import os
import sys
import time
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.approved_trade_liquidity_reroute")
_MARKER = "20260709k"
_PATCH_ATTR = "_nija_approved_trade_liquidity_reroute_v20260709k"
_TRUTHY = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in _TRUTHY


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        amount = float(value)
        if amount != amount:
            return default
        return amount
    except Exception:
        return default


def _symbol_from_sig(sig: Any) -> str:
    for attr in ("symbol", "pair", "ticker"):
        value = str(getattr(sig, attr, "") or "").strip().upper()
        if value:
            return value.replace("/", "-").replace("_", "-")
    return "UNKNOWN"


def _signal_score(sig: Any, payload: Any = None) -> float:
    for obj in (sig, payload if isinstance(payload, dict) else None):
        if obj is None:
            continue
        for name in ("composite_score", "entry_score", "score", "confidence"):
            try:
                value = getattr(obj, name, None) if obj is sig else obj.get(name)
                score = _f(value, 0.0)
                if score > 0:
                    return score
            except Exception:
                continue
    return 0.0


def _is_illiquid_hold(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    return (
        str(payload.get("action") or "").lower() == "hold"
        and str(payload.get("reason") or "").lower() == "fallback_illiquid_policy_blocked"
        and bool(payload.get("skip_before_execute_action") or payload.get("blocked_before_execute_action"))
    )


def _entry_ready(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    action = str(payload.get("action") or "").lower()
    if action not in {"enter_long", "enter_short", "buy", "sell"}:
        return False
    size = _f(payload.get("position_size") or payload.get("usd_size") or payload.get("notional") or payload.get("order_notional") or payload.get("final_order_notional"), 0.0)
    entry = _f(payload.get("entry_price") or payload.get("price") or payload.get("price_hint_usd"), 0.0)
    stop = _f(payload.get("stop_loss"), 0.0)
    tp = payload.get("take_profit")
    if isinstance(tp, dict):
        tp1 = _f(tp.get("tp1") or tp.get("target") or tp.get("price"), 0.0)
    else:
        tp1 = _f(tp, 0.0)
    return size > 0 and entry > 0 and stop > 0 and tp1 > 0


def _repair_payload_with_existing_safety(payload: Any, sig: Any, symbol: str) -> Any:
    if not isinstance(payload, dict):
        return payload
    try:
        import bot.forced_fallback_payload_repair_patch as repair
    except Exception:
        try:
            import forced_fallback_payload_repair_patch as repair  # type: ignore
        except Exception:
            return payload
    try:
        payload, changed, old_pct, new_pct = repair._cap_payload_geometry(payload)  # type: ignore[attr-defined]
        if changed:
            logger.critical(
                "CROSS_BROKER_LIQUIDITY_REROUTE_GEOMETRY_NORMALIZED marker=%s symbol=%s old_sl_pct=%.4f new_sl_pct=%.4f",
                _MARKER,
                symbol,
                old_pct,
                new_pct,
            )
    except Exception as exc:
        logger.debug("CROSS_BROKER_LIQUIDITY_REROUTE geometry repair skipped symbol=%s err=%s", symbol, exc)
    try:
        payload = repair._enforce_fallback_positive_ev(payload, sig=sig, symbol=symbol)  # type: ignore[attr-defined]
    except Exception as exc:
        logger.warning("CROSS_BROKER_LIQUIDITY_REROUTE positive_ev_check_failed marker=%s symbol=%s err=%s", _MARKER, symbol, exc)
    return payload


def _annotate_reroute(payload: dict[str, Any], symbol: str, score: float, original_hold: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    meta = dict(out.get("metadata") or {}) if isinstance(out.get("metadata"), dict) else {}
    meta["cross_broker_liquidity_reroute"] = True
    meta["original_liquidity_block_reason"] = original_hold.get("detail") or original_hold.get("reason")
    out["metadata"] = meta
    out["symbol"] = symbol
    out["broker_selected"] = None
    out["preferred_broker"] = None
    out["execution_broker"] = None
    out["broker"] = "auto"
    out["liquidity_reroute_required"] = True
    out["cross_broker_liquidity_reroute"] = True
    out["okx_only_liquidity_block_bypassed_for_reroute"] = True
    out["blocked_before_execute_action"] = False
    out["skip_before_execute_action"] = False
    out["order_should_not_submit"] = False
    out["fallback_entry_skipped"] = False
    reason = str(out.get("reason") or "fallback_entry")
    out["reason"] = f"{reason} [cross_broker_liquidity_reroute]"
    logger.critical(
        "CROSS_BROKER_LIQUIDITY_REROUTE marker=%s symbol=%s score=%.2f action=%s broker_before=okx broker_after=auto original_reason=%s",
        _MARKER,
        symbol,
        score,
        out.get("action"),
        original_hold.get("detail") or original_hold.get("reason"),
    )
    print(
        f"[NIJA-PRINT] CROSS_BROKER_LIQUIDITY_REROUTE marker={_MARKER} symbol={symbol} score={score:.2f} broker_after=auto",
        flush=True,
    )
    return out


def _patch_core_loop_module(module: ModuleType) -> bool:
    cls = getattr(module, "NijaCoreLoop", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "_build_forced_fallback_entry_analysis", None)
    if not callable(current) or getattr(current, _PATCH_ATTR, False):
        return bool(getattr(current, _PATCH_ATTR, False))
    base = getattr(current, "__wrapped__", current)

    @wraps(current)
    def _patched_build_forced_fallback_entry_analysis(self: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
        result = current(self, *args, **kwargs)
        if not _truthy("NIJA_APPROVED_TRADE_LIQUIDITY_REROUTE", True):
            return result
        if not _is_illiquid_hold(result):
            return result
        sig = kwargs.get("sig") if "sig" in kwargs else (args[1] if len(args) > 1 else None)
        symbol = _symbol_from_sig(sig)
        score = _signal_score(sig)
        min_score = _f(os.environ.get("NIJA_CROSS_BROKER_LIQUIDITY_REROUTE_MIN_SCORE"), 30.0)
        if score < min_score:
            logger.warning(
                "ALL_BROKERS_ILLIQUID_BLOCK marker=%s symbol=%s reason=score_below_reroute_floor score=%.2f floor=%.2f",
                _MARKER,
                symbol,
                score,
                min_score,
            )
            return result
        try:
            rebuilt = base(self, *args, **kwargs)
        except Exception as exc:
            logger.warning(
                "ALL_BROKERS_ILLIQUID_BLOCK marker=%s symbol=%s reason=base_payload_rebuild_failed err=%s",
                _MARKER,
                symbol,
                exc,
            )
            return result
        rebuilt = _repair_payload_with_existing_safety(rebuilt, sig, symbol)
        if _is_illiquid_hold(rebuilt) or not _entry_ready(rebuilt):
            logger.warning(
                "ALL_BROKERS_ILLIQUID_BLOCK marker=%s symbol=%s reason=rebuilt_payload_not_execution_ready rebuilt_action=%s rebuilt_reason=%s",
                _MARKER,
                symbol,
                getattr(rebuilt, "get", lambda k, d=None: d)("action") if isinstance(rebuilt, dict) else type(rebuilt).__name__,
                getattr(rebuilt, "get", lambda k, d=None: d)("reason") if isinstance(rebuilt, dict) else "non_dict",
            )
            return result
        return _annotate_reroute(rebuilt, symbol, score, result)

    setattr(_patched_build_forced_fallback_entry_analysis, _PATCH_ATTR, True)
    setattr(_patched_build_forced_fallback_entry_analysis, "__wrapped__", current)
    setattr(cls, "_build_forced_fallback_entry_analysis", _patched_build_forced_fallback_entry_analysis)
    logger.warning("APPROVED_TRADE_LIQUIDITY_REROUTE_PATCHED marker=%s module=%s", _MARKER, getattr(module, "__name__", "<unknown>"))
    print(f"[NIJA-PRINT] APPROVED_TRADE_LIQUIDITY_REROUTE_PATCHED marker={_MARKER} module={getattr(module, '__name__', '<unknown>')}", flush=True)
    return True


def _try_patch_loaded() -> bool:
    patched = False
    try:
        modules = list(sys.modules.items())
    except RuntimeError:
        modules = list(dict(sys.modules).items())
    for name, module in modules:
        if isinstance(module, ModuleType) and (name.endswith("core_loop") or hasattr(module, "NijaCoreLoop")):
            try:
                patched = _patch_core_loop_module(module) or patched
            except Exception as exc:
                logger.warning("APPROVED_TRADE_LIQUIDITY_REROUTE_PATCH_FAILED marker=%s module=%s err=%s", _MARKER, name, exc)
    return patched


def install_import_hook() -> None:
    _try_patch_loaded()
    if getattr(builtins, "_NIJA_APPROVED_TRADE_LIQUIDITY_REROUTE_HOOK_V20260709K", False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            if "core_loop" in str(name):
                _try_patch_loaded()
        except Exception as exc:
            logger.warning("APPROVED_TRADE_LIQUIDITY_REROUTE_IMPORT_HOOK_FAILED marker=%s name=%s err=%s", _MARKER, name, exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_APPROVED_TRADE_LIQUIDITY_REROUTE_HOOK_V20260709K", True)
    logger.warning("APPROVED_TRADE_LIQUIDITY_REROUTE_IMPORT_HOOK marker=%s", _MARKER)


def install() -> None:
    install_import_hook()
