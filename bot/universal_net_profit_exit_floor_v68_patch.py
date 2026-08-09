"""Universal fee-aware net-profit exit floor v68.

Normal take-profit decisions must represent net profit after round-trip trading
cost, spread and an exit slippage reserve.  Stored/gross TP values may not
bypass that invariant.  Protective exits remain separate:

* hard/explicit stop-loss exits are never delayed;
* trailing profit-lock callbacks may close once price is above fee-adjusted
  break-even, even if the full minimum-net-profit target is no longer available;
* normal take-profit exits require break-even + configured minimum net profit.

The resolver prefers broker/account runtime fee information when exposed and
falls back to NIJA's exchange capability matrix.  Unknown/future brokers receive
conservative defaults rather than a zero-fee assumption.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import math
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any, Mapping, Optional

LOGGER = logging.getLogger("nija.universal_net_profit_exit_floor_v68")
MARKER = "20260809-universal-net-profit-exit-floor-v68"
_PATCH_ATTR = "_nija_universal_net_profit_exit_floor_v68"
_INSTALL_LOCK = threading.RLock()

_PROTECTIVE_REASON_TOKENS = (
    "stop_loss", "emergency", "liquidation", "critical_margin", "max_loss", "risk_exit",
)
_TRAILING_REASON_TOKENS = (
    "profit_lock", "trailing", "break_even", "breakeven",
)
_PROFIT_REASON_TOKENS = (
    "take_profit", "profit_target", "net_profit", "harvest", "tp",
)


def _f(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value or 0.0)
    except (TypeError, ValueError, OverflowError):
        return default
    return result if math.isfinite(result) else default


def _broker_label(universal: ModuleType, broker: Any) -> str:
    try:
        return str(universal.auto_exit._broker_label(broker) or "unknown").strip().lower()
    except Exception:
        return "unknown"


def _extract_fee_value(value: Any) -> float:
    if isinstance(value, Mapping):
        for key in (
            "taker_fee", "taker", "fee_rate", "trading_fee", "commission_rate",
            "commission", "fee",
        ):
            if key in value:
                fee = _f(value.get(key), -1.0)
                if 0.0 <= fee <= 0.05:
                    return fee
        return -1.0
    fee = _f(value, -1.0)
    return fee if 0.0 <= fee <= 0.05 else -1.0


def _runtime_taker_fee(broker: Any, symbol: str) -> Optional[float]:
    """Return one-way taker fee from broker/account runtime data when available."""
    for method_name in (
        "get_taker_fee", "get_fee_rate", "get_trading_fee", "get_trading_fees",
        "get_fee_schedule", "get_fees",
    ):
        method = getattr(broker, method_name, None)
        if not callable(method):
            continue
        for args, kwargs in (
            ((symbol,), {}),
            ((), {"symbol": symbol}),
            ((), {}),
        ):
            try:
                result = method(*args, **kwargs)
            except TypeError:
                continue
            except Exception:
                break
            fee = _extract_fee_value(result)
            if fee >= 0.0:
                return fee
    for attr in (
        "taker_fee", "taker_fee_rate", "trading_fee", "fee_rate", "commission_rate",
    ):
        fee = _extract_fee_value(getattr(broker, attr, None))
        if fee >= 0.0:
            return fee
    return None


def _capability_round_trip_cost(broker_name: str, symbol: str) -> float:
    try:
        module = importlib.import_module("bot.exchange_capabilities")
        getter = getattr(module, "get_broker_capabilities", None)
        if callable(getter):
            caps = getter(broker_name, symbol)
            method = getattr(caps, "get_round_trip_fee", None)
            if callable(method):
                # Universal exits use market orders; taker economics are the
                # appropriate conservative fallback.
                value = _f(method(use_limit_order=False), 0.0)
                if 0.0 < value <= 0.20:
                    return value
    except Exception:
        pass
    # Unknown/future venue: conservative but bounded assumption, not zero cost.
    return max(0.0025, _f(os.environ.get("NIJA_UNKNOWN_BROKER_ROUND_TRIP_COST_PCT"), 0.004))


def _cost_model(universal: ModuleType, broker: Any, pos: Mapping[str, Any]) -> dict[str, float | str]:
    symbol = universal.auto_exit._sym(pos.get("symbol"))
    broker_name = _broker_label(universal, broker)
    runtime_fee = _runtime_taker_fee(broker, symbol)
    if runtime_fee is not None:
        spread = max(0.0, _f(os.environ.get("NIJA_EXIT_SPREAD_RESERVE_PCT"), 0.0010))
        round_trip = min(0.20, runtime_fee * 2.0 + spread)
        source = "broker_runtime_taker_fee"
    else:
        round_trip = _capability_round_trip_cost(broker_name, symbol)
        source = "exchange_capability_matrix"
    slippage = max(0.0, _f(os.environ.get("NIJA_EXIT_SLIPPAGE_RESERVE_PCT"), 0.0015))
    minimum_net = max(0.0, _f(os.environ.get("NIJA_MINIMUM_NET_PROFIT_PCT"), 0.0040))
    return {
        "round_trip": round_trip,
        "slippage": slippage,
        "minimum_net": minimum_net,
        "source": source,
    }


def _floors(universal: ModuleType, broker: Any, pos: Mapping[str, Any]) -> tuple[float, float, dict[str, Any]]:
    entry = universal.auto_exit._entry_price(dict(pos))
    if entry <= 0.0:
        return 0.0, 0.0, {}
    costs = _cost_model(universal, broker, pos)
    break_even_pct = float(costs["round_trip"]) + float(costs["slippage"])
    net_pct = break_even_pct + float(costs["minimum_net"])
    short = universal.auto_exit._side(pos.get("side"), dict(pos)) in {"short", "sell"}
    if short:
        break_even = entry * max(0.0, 1.0 - break_even_pct)
        net_target = entry * max(0.0, 1.0 - net_pct)
    else:
        break_even = entry * (1.0 + break_even_pct)
        net_target = entry * (1.0 + net_pct)
    details = dict(costs)
    details.update({
        "entry": entry,
        "break_even": break_even,
        "net_target": net_target,
        "short": short,
    })
    return break_even, net_target, details


def _meets(market: float, target: float, short: bool) -> bool:
    return market <= target if short else market >= target


def _reason_kind(reason: str) -> str:
    text = str(reason or "").strip().lower()
    if any(token in text for token in _PROTECTIVE_REASON_TOKENS):
        return "protective"
    if any(token in text for token in _TRAILING_REASON_TOKENS):
        return "trailing"
    if any(token in text for token in _PROFIT_REASON_TOKENS):
        return "profit"
    return "other"


def _patch_universal(module: ModuleType) -> bool:
    current = getattr(module, "_trigger", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    @wraps(current)
    def net_floor_trigger(broker: Any, pos: dict[str, Any], market: float):
        hit, reason, target = current(broker, pos, market)
        break_even, net_target, details = _floors(module, broker, pos)
        if break_even <= 0.0 or net_target <= 0.0:
            # Missing verified entry data: preserve existing protective behavior,
            # but do not synthesize a new profit trigger.
            return hit, reason, target
        short = bool(details.get("short"))
        kind = _reason_kind(reason) if hit else "none"

        if hit and kind == "protective":
            return hit, reason, target

        if hit and kind == "trailing":
            if _meets(market, break_even, short):
                LOGGER.info(
                    "UNIVERSAL_EXIT_V68_TRAILING_PROFIT_ALLOWED marker=%s venue=%s symbol=%s "
                    "market=%.8f break_even=%.8f net_target=%.8f source=%s",
                    MARKER, _broker_label(module, broker), module.auto_exit._sym(pos.get("symbol")),
                    market, break_even, net_target, details.get("source"),
                )
                return hit, reason, max(target, break_even) if not short else min(target or break_even, break_even)
            LOGGER.warning(
                "UNIVERSAL_EXIT_V68_TRAILING_BELOW_COST_SUPPRESSED marker=%s venue=%s symbol=%s "
                "reason=%s market=%.8f break_even=%.8f",
                MARKER, _broker_label(module, broker), module.auto_exit._sym(pos.get("symbol")),
                reason, market, break_even,
            )
            return False, "", 0.0

        if hit and kind in {"profit", "other"}:
            if _meets(market, net_target, short):
                LOGGER.critical(
                    "UNIVERSAL_EXIT_V68_NET_PROFIT_READY marker=%s venue=%s symbol=%s reason=%s "
                    "market=%.8f net_target=%.8f break_even=%.8f round_trip=%.5f slippage=%.5f min_net=%.5f source=%s",
                    MARKER, _broker_label(module, broker), module.auto_exit._sym(pos.get("symbol")), reason,
                    market, net_target, break_even, details.get("round_trip", 0.0),
                    details.get("slippage", 0.0), details.get("minimum_net", 0.0), details.get("source"),
                )
                return True, reason or "net_profit_target", net_target
            LOGGER.warning(
                "UNIVERSAL_EXIT_V68_GROSS_TP_SUPPRESSED marker=%s venue=%s symbol=%s reason=%s "
                "market=%.8f stored_target=%.8f required_net_target=%.8f source=%s",
                MARKER, _broker_label(module, broker), module.auto_exit._sym(pos.get("symbol")),
                reason or "unknown", market, target, net_target, details.get("source"),
            )
            return False, "", 0.0

        # No legacy trigger: let the universal net floor itself create the TP.
        if not hit and _meets(market, net_target, short):
            LOGGER.critical(
                "UNIVERSAL_EXIT_V68_NET_PROFIT_TARGET_TRIGGERED marker=%s venue=%s symbol=%s "
                "market=%.8f net_target=%.8f source=%s",
                MARKER, _broker_label(module, broker), module.auto_exit._sym(pos.get("symbol")),
                market, net_target, details.get("source"),
            )
            return True, "net_profit_target", net_target
        return hit, reason, target

    setattr(net_floor_trigger, _PATCH_ATTR, True)
    setattr(net_floor_trigger, "__wrapped__", current)
    module._trigger = net_floor_trigger
    LOGGER.critical(
        "UNIVERSAL_NET_PROFIT_EXIT_FLOOR_V68_PATCHED marker=%s module=%s "
        "gross_tp_bypass=false emergency_exits_unchanged=true",
        MARKER,
        module.__name__,
    )
    return True


def _patch_loaded() -> bool:
    changed = False
    for name in ("bot.universal_broker_exit_supervisor_patch", "universal_broker_exit_supervisor_patch"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            changed = _patch_universal(module) or changed
    return changed


def install_import_hook() -> bool:
    with _INSTALL_LOCK:
        try:
            importlib.import_module("bot.universal_broker_exit_supervisor_patch")
        except Exception:
            pass
        _patch_loaded()
        flag = "_NIJA_UNIVERSAL_NET_PROFIT_EXIT_FLOOR_V68_IMPORT_HOOK"
        if getattr(builtins, flag, False):
            return True
        original_import = builtins.__import__

        @wraps(original_import)
        def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
            result = original_import(name, globals, locals, fromlist, level)
            if "universal_broker_exit" in str(name):
                _patch_loaded()
            return result

        builtins.__import__ = guarded_import
        setattr(builtins, flag, True)
        os.environ["NIJA_UNIVERSAL_NET_PROFIT_EXIT_FLOOR_V68_INSTALLED"] = "1"
        LOGGER.critical(
            "UNIVERSAL_NET_PROFIT_EXIT_FLOOR_V68_INSTALLED marker=%s fee_aware=true",
            MARKER,
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "install", "install_import_hook", "_cost_model", "_floors", "_reason_kind"]
