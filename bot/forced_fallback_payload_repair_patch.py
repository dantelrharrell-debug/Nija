from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.forced_fallback_payload_repair")
_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_PATCHED = False
_MONITOR_STARTED = False
_INSTALL_LOCK = threading.Lock()
_TRUTHY = {"1", "true", "yes", "enabled", "on", "y"}
_WRAP_ATTR = "_nija_forced_fallback_payload_repair_wrapped_v20260703t"

_FALLBACK_HARD_MAX_SL_PCT = 0.0028
_FALLBACK_DEFAULT_SL_PCT = 0.0025
_FALLBACK_MIN_SL_PCT = 0.0015
_ILLQUID_POLICY_TEXT = "competitive profitability policy blocked illiquid fallback entry"
_MIN_EXPECTANCY_MARGIN = 0.0001


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUTHY


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default) or default)
    except Exception:
        return default


def _wrapper_chain_has_attr(fn: Any, attr: str) -> bool:
    seen: set[int] = set()
    cur = fn
    while callable(cur) and id(cur) not in seen:
        seen.add(id(cur))
        if getattr(cur, attr, False):
            return True
        cur = getattr(cur, "__wrapped__", None)
    return False


def _coerce_probability(value: Any) -> float:
    try:
        p = float(value)
    except Exception:
        return 0.0
    if p > 1.0:
        p = p / 100.0
    return max(0.0, min(p, 1.0))


def _coerce_price(value: Any) -> float:
    if isinstance(value, dict):
        for key in ("tp1", "target", "price", "take_profit", "value", "level"):
            try:
                p = float(value.get(key) or 0.0)
                if p > 0.0:
                    return p
            except Exception:
                pass
        return 0.0
    if isinstance(value, (list, tuple)):
        for item in value:
            p = _coerce_price(item)
            if p > 0.0:
                return p
        return 0.0
    try:
        p = float(value or 0.0)
        return p if p > 0.0 else 0.0
    except Exception:
        return 0.0


def _symbol_from_sig(sig: Any) -> str:
    return str(getattr(sig, "symbol", "UNKNOWN") or "UNKNOWN")


def _hold_skip(symbol: str, *, reason: str, stage: str, detail: str = "") -> dict[str, Any]:
    return {
        "action": "hold",
        "reason": reason,
        "filter_stage": stage,
        "detail": detail,
        "symbol": symbol,
        "blocked_before_execute_action": True,
        "skip_before_execute_action": True,
        "fallback_entry_skipped": True,
        "forced_fallback": False,
        "fallback_entry": False,
        "order_should_not_submit": True,
    }


def _signal_expected_win_rate(sig: Any) -> float:
    for name in (
        "expected_win_rate",
        "win_rate",
        "win_probability",
        "probability_of_success",
        "success_probability",
        "edge_probability",
    ):
        p = _coerce_probability(getattr(sig, name, None))
        if p > 0.0:
            return p
    try:
        analysis = getattr(sig, "analysis", None)
        if isinstance(analysis, dict):
            for name in (
                "expected_win_rate",
                "win_rate",
                "win_probability",
                "probability_of_success",
                "success_probability",
                "edge_probability",
            ):
                p = _coerce_probability(analysis.get(name))
                if p > 0.0:
                    return p
    except Exception:
        pass
    return 0.0


def _fallback_sl_pct() -> float:
    requested = _float_env("NIJA_FALLBACK_REPAIR_SL_PCT", _FALLBACK_DEFAULT_SL_PCT)
    return max(_FALLBACK_MIN_SL_PCT, min(requested, _FALLBACK_HARD_MAX_SL_PCT))


def _payload_ev(payload: Any) -> tuple[bool, str, float, float, float]:
    if not isinstance(payload, dict):
        return True, "non_dict_payload", 0.0, 0.0, 0.0
    if not bool(payload.get("fallback_entry") or payload.get("forced_fallback")):
        return True, "not_fallback", 0.0, 0.0, 0.0
    try:
        entry = float(payload.get("entry_price") or 0.0)
        stop = float(payload.get("stop_loss") or 0.0)
        take_profit = payload.get("take_profit")
        expected_wr = 0.0
        if isinstance(take_profit, dict):
            tp1 = _coerce_price(take_profit.get("tp1") or take_profit.get("target") or take_profit.get("price") or take_profit.get("levels"))
            expected_wr = _coerce_probability(take_profit.get("expected_win_rate"))
        elif isinstance(take_profit, (list, tuple)):
            tp1 = _coerce_price(take_profit)
            for item in take_profit:
                if isinstance(item, dict):
                    expected_wr = max(expected_wr, _coerce_probability(item.get("expected_win_rate") or item.get("win_rate") or item.get("probability")))
        else:
            tp1 = _coerce_price(take_profit)
    except Exception as exc:
        return False, f"fallback_ev_unavailable:{exc}", 0.0, 0.0, 0.0
    if entry <= 0.0 or stop <= 0.0 or tp1 <= 0.0:
        return False, "fallback_ev_missing_price_geometry", expected_wr, 0.0, 0.0
    win_pct = abs(tp1 - entry) / entry
    loss_pct = abs(entry - stop) / entry
    fee_pct = _float_env("NIJA_FALLBACK_PREFLIGHT_ROUND_TRIP_FEE_PCT", 0.003)
    net_win = max(0.0, win_pct - fee_pct)
    net_loss = loss_pct + fee_pct
    if net_win <= 0.0:
        return False, f"fallback_net_win_nonpositive win_pct={win_pct:.4f} fee_pct={fee_pct:.4f}", expected_wr, 1.0, -net_loss
    breakeven = net_loss / (net_win + net_loss)
    expectancy_pct = (expected_wr * net_win) - ((1.0 - expected_wr) * net_loss)
    ok = expected_wr > 0.0 and expectancy_pct > _MIN_EXPECTANCY_MARGIN and expected_wr > breakeven
    detail = (
        f"expected_wr={expected_wr:.4f} breakeven_wr={breakeven:.4f} "
        f"expectancy_pct={expectancy_pct:.4f} win_pct={win_pct:.4f} loss_pct={loss_pct:.4f} fee_pct={fee_pct:.4f}"
    )
    return ok, detail, expected_wr, breakeven, expectancy_pct


def _enforce_fallback_positive_ev(payload: Any, *, sig: Any, symbol: str) -> Any:
    if not isinstance(payload, dict):
        return payload
    tp = payload.get("take_profit")
    explicit_wr = _signal_expected_win_rate(sig)
    if explicit_wr > 0.0:
        if isinstance(tp, dict):
            tp["expected_win_rate"] = explicit_wr
        elif isinstance(tp, list):
            for item in tp:
                if isinstance(item, dict):
                    item["expected_win_rate"] = explicit_wr
    ok, detail, expected_wr, breakeven, expectancy_pct = _payload_ev(payload)
    if ok:
        return payload
    logger.warning(
        "FORCED_FALLBACK_POSITIVE_EV_PREFILTER_SKIPPED marker=20260703t symbol=%s detail=%s action=hold_skip_before_execute",
        symbol,
        detail,
    )
    print(
        f"[NIJA-PRINT] FORCED_FALLBACK_POSITIVE_EV_PREFILTER_SKIPPED marker=20260703t symbol={symbol} "
        f"expected_wr={expected_wr:.4f} breakeven_wr={breakeven:.4f} expectancy_pct={expectancy_pct:.4f}",
        flush=True,
    )
    return _hold_skip(symbol, reason="fallback_positive_ev_prefilter_blocked", stage="fallback_positive_ev_prefilter", detail=detail)


def _cap_payload_geometry(payload: Any) -> tuple[Any, bool, float, float]:
    if not isinstance(payload, dict):
        return payload, False, 0.0, 0.0
    try:
        price = float(payload.get("entry_price") or 0.0)
        stop = float(payload.get("stop_loss") or 0.0)
    except Exception:
        return payload, False, 0.0, 0.0
    if price <= 0.0 or stop <= 0.0:
        return payload, False, 0.0, 0.0
    old_sl_pct = abs((price - stop) / price)
    capped_pct = _fallback_sl_pct()
    if old_sl_pct <= capped_pct:
        return payload, False, old_sl_pct, old_sl_pct
    action = str(payload.get("action") or "enter_long").lower()
    payload["stop_loss"] = price * (1.0 + capped_pct) if action == "enter_short" else price * (1.0 - capped_pct)
    tp = payload.get("take_profit")
    if isinstance(tp, dict):
        tp["fallback_sl_pct"] = capped_pct
        tp["fallback_max_sl_pct"] = _FALLBACK_HARD_MAX_SL_PCT
    elif isinstance(tp, list):
        for item in tp:
            if isinstance(item, dict):
                item["fallback_sl_pct"] = capped_pct
                item["fallback_max_sl_pct"] = _FALLBACK_HARD_MAX_SL_PCT
    payload["fallback_target_geometry_capped"] = True
    payload["fallback_edge_geometry_repaired"] = True
    payload["reason"] = str(payload.get("reason") or "fallback_entry") + " [fallback_target_geometry_capped]"
    return payload, True, old_sl_pct, capped_pct


def _install_on_module(module: ModuleType) -> bool:
    global _PATCHED
    cls = getattr(module, "NijaCoreLoop", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "_build_forced_fallback_entry_analysis", None)
    if not callable(original):
        return False
    if _wrapper_chain_has_attr(original, _WRAP_ATTR):
        _PATCHED = True
        return True

    def _patched_build_forced_fallback_entry_analysis(self: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
        sig = kwargs.get("sig") if "sig" in kwargs else (args[1] if len(args) > 1 else None)
        symbol = _symbol_from_sig(sig)
        try:
            payload = original(self, *args, **kwargs)
            payload, changed, old_pct, new_pct = _cap_payload_geometry(payload)
            if changed:
                logger.critical(
                    "FORCED_FALLBACK_PAYLOAD_GEOMETRY_NORMALIZED marker=20260703t symbol=%s old_sl_pct=%.4f new_sl_pct=%.4f",
                    symbol, old_pct, new_pct,
                )
                print(
                    f"[NIJA-PRINT] FORCED_FALLBACK_PAYLOAD_GEOMETRY_NORMALIZED marker=20260703t | symbol={symbol} "
                    f"old_sl_pct={old_pct * 100.0:.3f}% new_sl_pct={new_pct * 100.0:.3f}%",
                    flush=True,
                )
            return _enforce_fallback_positive_ev(payload, sig=sig, symbol=symbol)
        except ValueError as exc:
            message = str(exc)
            if _ILLQUID_POLICY_TEXT in message or "competitive profitability policy" in message:
                logger.warning(
                    "FORCED_FALLBACK_PAYLOAD_REPAIR_SKIPPED marker=20260703t symbol=%s reason=%s action=hold_skip_before_execute",
                    symbol, message,
                )
                print(
                    f"[NIJA-PRINT] FORCED_FALLBACK_PAYLOAD_REPAIR_SKIPPED marker=20260703t symbol={symbol} reason=illiquid_policy_block",
                    flush=True,
                )
                return _hold_skip(symbol, reason="fallback_illiquid_policy_blocked", stage="competitive_profitability_policy", detail=message)
            if "fallback positive-EV prefilter blocked execution" in message:
                logger.warning(
                    "FORCED_FALLBACK_POSITIVE_EV_PREFILTER_SKIPPED marker=20260703t symbol=%s detail=%s action=hold_skip_before_execute",
                    symbol, message,
                )
                return _hold_skip(symbol, reason="fallback_positive_ev_prefilter_blocked", stage="fallback_positive_ev_prefilter", detail=message)
            raise

    setattr(_patched_build_forced_fallback_entry_analysis, _WRAP_ATTR, True)
    setattr(_patched_build_forced_fallback_entry_analysis, "__wrapped__", original)
    setattr(cls, "_build_forced_fallback_entry_analysis", _patched_build_forced_fallback_entry_analysis)
    _PATCHED = True
    logger.warning("FORCED_FALLBACK_PAYLOAD_REPAIR_PATCHED marker=20260703t module=%s", getattr(module, "__name__", "<unknown>"))
    print(f"[NIJA-PRINT] FORCED_FALLBACK_PAYLOAD_REPAIR_PATCHED marker=20260703t | module={getattr(module, '__name__', '<unknown>')}", flush=True)
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name, module in list(sys.modules.items()):
        if not isinstance(module, ModuleType):
            continue
        if name in {"bot.nija_core_loop", "nija_core_loop"} or hasattr(module, "NijaCoreLoop"):
            patched = _install_on_module(module) or patched
    return patched


def _start_module_monitor() -> None:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    _MONITOR_STARTED = True

    def _monitor() -> None:
        deadline = time.time() + float(os.environ.get("NIJA_PATCH_MONITOR_SECONDS", "300") or "300")
        patched_any = False
        while time.time() < deadline:
            patched_any = _try_patch_loaded() or patched_any
            time.sleep(1.0)
        logger.warning("FORCED_FALLBACK_PAYLOAD_REPAIR_MONITOR_COMPLETE marker=20260703t patched=%s patched_any=%s", _PATCHED, patched_any)

    threading.Thread(target=_monitor, name="forced-fallback-payload-repair-monitor", daemon=True).start()
    logger.warning("FORCED_FALLBACK_PAYLOAD_REPAIR_MONITOR_STARTED marker=20260703t")


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    with _INSTALL_LOCK:
        _try_patch_loaded()
        _start_module_monitor()
        if _ORIGINAL_IMPORT_MODULE is not None:
            logger.warning("FORCED_FALLBACK_PAYLOAD_REPAIR_INSTALL_COMPLETE marker=20260703t already_installed=True patched=%s", _PATCHED)
            return
        _ORIGINAL_IMPORT_MODULE = importlib.import_module

        def _wrapped_import_module(name: str, package: str | None = None):
            module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
            if name in {"bot.nija_core_loop", "nija_core_loop"} or hasattr(module, "NijaCoreLoop"):
                _install_on_module(module)
            _try_patch_loaded()
            return module

        importlib.import_module = _wrapped_import_module  # type: ignore[assignment]
        logger.warning("FORCED_FALLBACK_PAYLOAD_REPAIR_INSTALL_COMPLETE marker=20260703t patched=%s", _PATCHED)
