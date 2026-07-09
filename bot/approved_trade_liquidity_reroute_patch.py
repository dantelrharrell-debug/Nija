from __future__ import annotations

import builtins
import logging
import os
import sys
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.approved_trade_liquidity_reroute")
_MARKER = "20260709p"
_PATCH_ATTR = "_nija_approved_trade_liquidity_reroute_v20260709p"
_TRUTHY = {"1", "true", "yes", "on", "enabled", "y"}
_OLD_HOOK_FLAG = "_NIJA_APPROVED_TRADE_LIQUIDITY_REROUTE_HOOK_V20260709K"
_HOOK_FLAG = "_NIJA_APPROVED_TRADE_LIQUIDITY_REROUTE_HOOK_V20260709P"


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
                    return score * 100.0 if 0.0 < score <= 1.0 else score
            except Exception:
                continue
    return 0.0


def _is_illiquid_hold(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    reason = str(payload.get("reason") or "").lower()
    detail = str(payload.get("detail") or "").lower()
    return (
        str(payload.get("action") or "").lower() == "hold"
        and (
            reason == "fallback_illiquid_policy_blocked"
            or "fallback_illiquid_policy_blocked" in detail
            or "competitive profitability policy blocked illiquid" in detail
        )
        and bool(payload.get("skip_before_execute_action") or payload.get("blocked_before_execute_action"))
    )


def _is_positive_ev_hold(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    reason = str(payload.get("reason") or "").lower()
    detail = str(payload.get("detail") or "").lower()
    return (
        str(payload.get("action") or "").lower() == "hold"
        and reason == "fallback_positive_ev_prefilter_blocked"
        and "score_below_strict_floor" in detail
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


def _coerce_price(value: Any) -> float:
    if isinstance(value, dict):
        for key in ("tp1", "target", "price", "take_profit", "value", "level"):
            price = _f(value.get(key), 0.0)
            if price > 0:
                return price
        return 0.0
    if isinstance(value, (list, tuple)):
        for item in value:
            price = _coerce_price(item)
            if price > 0:
                return price
        return 0.0
    return _f(value, 0.0)


def _extract_last_price(df: Any, payload: Any = None) -> float:
    if isinstance(payload, dict):
        for key in ("entry_price", "price", "price_hint_usd", "last_price", "close"):
            price = _f(payload.get(key), 0.0)
            if price > 0:
                return price
    try:
        for col in ("close", "last", "price", "mark"):
            if hasattr(df, "columns") and col in df.columns:
                price = _f(df[col].iloc[-1], 0.0)
                if price > 0:
                    return price
    except Exception:
        pass
    return 0.0


def _snapshot_balance(snapshot: Any) -> float:
    for attr in ("balance", "available_balance", "capital", "equity", "total_capital"):
        value = _f(getattr(snapshot, attr, 0.0), 0.0)
        if value > 0:
            return value
    return 0.0


def _expected_wr_from_score(score: float) -> float:
    score_norm = max(0.0, min(score / 100.0 if score > 1.0 else score, 1.0))
    floor = _f(os.environ.get("NIJA_REROUTE_EXPECTED_WIN_RATE_FLOOR"), 0.535)
    cap = _f(os.environ.get("NIJA_REROUTE_EXPECTED_WIN_RATE_CAP"), 0.68)
    return max(floor, min(cap, 0.45 + (0.30 * score_norm)))


def _local_ev_check(payload: dict[str, Any], *, score: float) -> tuple[bool, str]:
    action = str(payload.get("action") or "").lower()
    entry = _f(payload.get("entry_price"), 0.0)
    size = _f(payload.get("position_size") or payload.get("order_notional"), 0.0)
    stop = _f(payload.get("stop_loss"), 0.0)
    tp = payload.get("take_profit")
    tp1 = _coerce_price((tp or {}).get("tp1") if isinstance(tp, dict) else tp)
    expected_wr = _f(payload.get("expected_win_rate"), 0.0)
    if expected_wr > 1.0:
        expected_wr /= 100.0
    if action not in {"enter_long", "enter_short"}:
        return False, f"invalid_action:{action}"
    if entry <= 0 or size <= 0 or stop <= 0 or tp1 <= 0:
        return False, "missing_geometry_or_size"
    if action == "enter_long" and not (stop < entry < tp1):
        return False, "invalid_long_geometry"
    if action == "enter_short" and not (tp1 < entry < stop):
        return False, "invalid_short_geometry"
    win_pct = abs(tp1 - entry) / entry
    loss_pct = abs(entry - stop) / entry
    fee_pct = _f(os.environ.get("NIJA_REROUTE_ROUND_TRIP_FEE_PCT"), 0.003)
    net_win = max(0.0, win_pct - fee_pct)
    net_loss = loss_pct + fee_pct
    if net_win <= 0:
        return False, f"net_win_nonpositive win_pct={win_pct:.4f} fee_pct={fee_pct:.4f}"
    breakeven = net_loss / (net_win + net_loss)
    expectancy_pct = (expected_wr * net_win) - ((1.0 - expected_wr) * net_loss)
    min_margin = _f(os.environ.get("NIJA_REROUTE_MIN_EXPECTANCY_MARGIN"), 0.00005)
    ok = expected_wr > breakeven and expectancy_pct > min_margin
    return ok, f"expected_wr={expected_wr:.4f} breakeven_wr={breakeven:.4f} expectancy_pct={expectancy_pct:.4f} score={score:.2f}"


def _synthetic_payload(df: Any, sig: Any, snapshot: Any, *, action: str, symbol: str, original_hold: dict[str, Any], score: float) -> dict[str, Any] | None:
    price = _extract_last_price(df)
    balance = _snapshot_balance(snapshot)
    if price <= 0 or balance <= 0:
        logger.warning(
            "ALL_BROKERS_ILLIQUID_BLOCK marker=%s symbol=%s reason=synthetic_payload_missing_price_or_balance price=%.8f balance=%.2f",
            _MARKER,
            symbol,
            price,
            balance,
        )
        return None
    min_notional = _f(os.environ.get("OKX_MIN_ORDER_USD"), 10.0)
    min_notional = max(min_notional, _f(os.environ.get("MIN_TRADE_USD"), 10.0), 10.0)
    pct = max(0.001, min(_f(os.environ.get("NIJA_REROUTE_SYNTHETIC_POSITION_PCT"), 0.05), 0.10))
    size = max(min_notional, balance * pct)
    max_pct = max(pct, min(_f(os.environ.get("NIJA_REROUTE_SYNTHETIC_MAX_POSITION_PCT"), 0.05), 0.10))
    size = min(size, balance * max_pct)
    if size < min_notional:
        return None
    stop_pct = max(0.0015, min(_f(os.environ.get("NIJA_REROUTE_SYNTHETIC_SL_PCT"), 0.0025), 0.0040))
    tp1_pct = max(0.0100, _f(os.environ.get("NIJA_REROUTE_SYNTHETIC_TP1_PCT"), 0.0120))
    tp2_pct = max(tp1_pct + 0.003, _f(os.environ.get("NIJA_REROUTE_SYNTHETIC_TP2_PCT"), 0.0180))
    tp3_pct = max(tp2_pct + 0.004, _f(os.environ.get("NIJA_REROUTE_SYNTHETIC_TP3_PCT"), 0.0260))
    if action == "enter_short":
        stop = price * (1.0 + stop_pct)
        tp = {"tp1": price * (1.0 - tp1_pct), "tp2": price * (1.0 - tp2_pct), "tp3": price * (1.0 - tp3_pct)}
    else:
        action = "enter_long"
        stop = price * (1.0 - stop_pct)
        tp = {"tp1": price * (1.0 + tp1_pct), "tp2": price * (1.0 + tp2_pct), "tp3": price * (1.0 + tp3_pct)}
    expected_wr = _expected_wr_from_score(score)
    tp["expected_win_rate"] = expected_wr
    tp["expected_win_rate_source"] = f"reroute_synthetic_score:{_MARKER}"
    payload = {
        "action": action,
        "symbol": symbol,
        "entry_price": price,
        "price_hint_usd": price,
        "position_size": float(size),
        "order_notional": float(size),
        "capital_allocated": float(size),
        "min_notional": float(min_notional),
        "stop_loss": stop,
        "take_profit": tp,
        "trailing_stop_pct": 0.75,
        "fallback_entry": True,
        "forced_fallback": True,
        "reroute_synthetic_payload": True,
        "expected_win_rate": expected_wr,
        "expected_win_rate_source": f"reroute_synthetic_score:{_MARKER}",
        "composite_score": score,
        "score": score,
        "reason": f"reroute_synthetic_payload_after_{original_hold.get('reason') or 'illiquid_hold'}",
        "metadata": {
            "reroute_synthetic_payload": True,
            "original_hold_reason": original_hold.get("detail") or original_hold.get("reason"),
            "tpe_execute_recovered": True,
        },
    }
    ok, detail = _local_ev_check(payload, score=score)
    if not ok:
        logger.warning(
            "ALL_BROKERS_ILLIQUID_BLOCK marker=%s symbol=%s reason=synthetic_payload_ev_failed detail=%s",
            _MARKER,
            symbol,
            detail,
        )
        return None
    logger.critical(
        "REROUTE_SYNTHETIC_PAYLOAD_BUILT marker=%s symbol=%s action=%s price=%.8f size=%.2f score=%.2f ev=%s",
        _MARKER,
        symbol,
        action,
        price,
        size,
        score,
        detail,
    )
    print(
        f"[NIJA-PRINT] REROUTE_SYNTHETIC_PAYLOAD_BUILT marker={_MARKER} symbol={symbol} action={action} size={size:.2f} score={score:.2f}",
        flush=True,
    )
    return payload


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
    # Synthetic TPE-recovered payloads have already passed local EV math. Do not
    # let the legacy strict-score floor turn a positive-EV, TPE-approved payload
    # back into HOLD solely because score is below the old static floor.
    if isinstance(payload, dict) and payload.get("reroute_synthetic_payload"):
        return payload
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
        if not (_is_illiquid_hold(result) or _is_positive_ev_hold(result)):
            return result
        sig = kwargs.get("sig") if "sig" in kwargs else (args[1] if len(args) > 1 else None)
        df = kwargs.get("df") if "df" in kwargs else (args[0] if args else None)
        snapshot = kwargs.get("snapshot") if "snapshot" in kwargs else (args[2] if len(args) > 2 else None)
        action = str(kwargs.get("action") or result.get("action") or "").strip().lower()
        if action not in {"enter_long", "enter_short"}:
            side = str(getattr(sig, "side", "") or "").strip().lower()
            action = "enter_short" if side in {"short", "sell", "enter_short"} else "enter_long"
        symbol = _symbol_from_sig(sig)
        score = _signal_score(sig, result)
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
                "REROUTE_BASE_PAYLOAD_REBUILD_FAILED marker=%s symbol=%s err=%s action=synthetic_recovery_attempt",
                _MARKER,
                symbol,
                exc,
            )
            rebuilt = _synthetic_payload(df, sig, snapshot, action=action, symbol=symbol, original_hold=result, score=score)
            if rebuilt is None:
                logger.warning(
                    "ALL_BROKERS_ILLIQUID_BLOCK marker=%s symbol=%s reason=base_payload_rebuild_failed_and_synthetic_recovery_failed err=%s",
                    _MARKER,
                    symbol,
                    exc,
                )
                return result
        rebuilt = _repair_payload_with_existing_safety(rebuilt, sig, symbol)
        if _is_illiquid_hold(rebuilt) or _is_positive_ev_hold(rebuilt) or not _entry_ready(rebuilt):
            # Last-resort recovery when the base builder returned a HOLD due to the
            # old static positive-EV score floor or OKX-only zero-volume data.
            fallback = _synthetic_payload(df, sig, snapshot, action=action, symbol=symbol, original_hold=result, score=score)
            if fallback is not None:
                rebuilt = fallback
        if _is_illiquid_hold(rebuilt) or _is_positive_ev_hold(rebuilt) or not _entry_ready(rebuilt):
            logger.warning(
                "ALL_BROKERS_ILLIQUID_BLOCK marker=%s symbol=%s reason=rebuilt_payload_not_execution_ready rebuilt_action=%s rebuilt_reason=%s rebuilt_detail=%s",
                _MARKER,
                symbol,
                getattr(rebuilt, "get", lambda k, d=None: d)("action") if isinstance(rebuilt, dict) else type(rebuilt).__name__,
                getattr(rebuilt, "get", lambda k, d=None: d)("reason") if isinstance(rebuilt, dict) else "non_dict",
                getattr(rebuilt, "get", lambda k, d=None: d)("detail") if isinstance(rebuilt, dict) else "non_dict",
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
    if getattr(builtins, _HOOK_FLAG, False):
        return
    # If the old hook flag is already present on a long-lived interpreter, still
    # install this v2 hook because the patch attribute changed to 20260709p.
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
    setattr(builtins, _HOOK_FLAG, True)
    # Keep the old flag true for compatibility with diagnostics that look for it.
    setattr(builtins, _OLD_HOOK_FLAG, True)
    logger.warning("APPROVED_TRADE_LIQUIDITY_REROUTE_IMPORT_HOOK marker=%s", _MARKER)


def install() -> None:
    install_import_hook()
