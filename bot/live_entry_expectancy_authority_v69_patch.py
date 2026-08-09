"""Live entry expectancy authority v69.

NIJA already ships ``TradeExpectancyValidator`` with a documented minimum
acceptable 1.5R and first-move confirmation standard, but the APEX live path can
later treat poor trade math as advisory and can lower entry gates during a trade
drought.  v69 makes the existing expectancy standard authoritative at the final
strategy-output boundary in live-capital mode.

A live entry must therefore prove:

* valid positive entry/stop/first-target geometry;
* raw first-target reward/risk >= the existing 1.5R acceptable threshold;
* first-move confirmation (volume expansion OR range expansion) from the
  existing validator;
* first-target reward after estimated round-trip taker cost and slippage still
  leaves at least ``NIJA_MINIMUM_NET_PROFIT_PCT`` net edge;
* diagnostic market/smart-filter bypass flags cannot remain active in live mode;
* drought/fallback logic cannot reduce the live gate below its normal configured
  baseline merely because no trade has occurred recently.

The patch does not create signals, loosen risk limits, or guarantee profitable
trades.  Non-live diagnostic/paper behavior remains available.
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

LOGGER = logging.getLogger("nija.live_entry_expectancy_authority_v69")
MARKER = "20260809-live-entry-expectancy-authority-v69"
_PATCH_ATTR = "_nija_live_entry_expectancy_authority_v69"
_INSTALL_LOCK = threading.RLock()
_VALIDATOR: Any = None


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in {
        "1", "true", "yes", "on", "enabled", "y",
    }


def _live_mode() -> bool:
    return bool(
        _truthy("LIVE_CAPITAL_VERIFIED", "false")
        and not _truthy("DRY_RUN_MODE", "false")
        and not _truthy("PAPER_MODE", "false")
    )


def _f(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value or 0.0)
    except (TypeError, ValueError, OverflowError):
        return default
    return result if math.isfinite(result) else default


def _first_target(value: Any) -> float:
    if isinstance(value, Mapping):
        for key in ("tp1", "take_profit_1", "first", "target", "price"):
            target = _f(value.get(key))
            if target > 0.0:
                return target
        numeric = [_f(v) for v in value.values()]
        numeric = [v for v in numeric if v > 0.0]
        return min(numeric) if numeric else 0.0
    if isinstance(value, (list, tuple)):
        for item in value:
            target = _f(item)
            if target > 0.0:
                return target
        return 0.0
    return _f(value)


def _validator() -> Any:
    global _VALIDATOR
    if _VALIDATOR is None:
        try:
            module = importlib.import_module("bot.trade_expectancy_validator")
        except ImportError:
            module = importlib.import_module("trade_expectancy_validator")
        _VALIDATOR = module.TradeExpectancyValidator(strict_mode=False)
    return _VALIDATOR


def _runtime_taker_fee(broker: Any, symbol: str) -> Optional[float]:
    for method_name in (
        "get_taker_fee", "get_fee_rate", "get_trading_fee", "get_trading_fees",
        "get_fee_schedule", "get_fees",
    ):
        method = getattr(broker, method_name, None)
        if not callable(method):
            continue
        for args, kwargs in (((symbol,), {}), ((), {"symbol": symbol}), ((), {})):
            try:
                result = method(*args, **kwargs)
            except TypeError:
                continue
            except Exception:
                break
            if isinstance(result, Mapping):
                values = [
                    result.get("taker_fee"), result.get("taker"), result.get("fee_rate"),
                    result.get("trading_fee"), result.get("commission_rate"), result.get("fee"),
                ]
            else:
                values = [result]
            for value in values:
                fee = _f(value, -1.0)
                if 0.0 <= fee <= 0.05:
                    return fee
    for attr in ("taker_fee", "taker_fee_rate", "trading_fee", "fee_rate", "commission_rate"):
        fee = _f(getattr(broker, attr, None), -1.0)
        if 0.0 <= fee <= 0.05:
            return fee
    return None


def _broker_name(strategy: Any) -> str:
    getter = getattr(strategy, "_get_broker_name", None)
    if callable(getter):
        try:
            name = str(getter() or "").strip().lower()
            if name:
                return name
        except Exception:
            pass
    broker = getattr(strategy, "broker_client", None)
    broker_type = getattr(broker, "broker_type", None)
    return str(getattr(broker_type, "value", broker_type) or type(broker).__name__).strip().lower()


def _round_trip_cost(strategy: Any, symbol: str) -> tuple[float, str]:
    broker = getattr(strategy, "broker_client", None)
    runtime_fee = _runtime_taker_fee(broker, symbol) if broker is not None else None
    spread_reserve = max(0.0, _f(os.environ.get("NIJA_ENTRY_SPREAD_RESERVE_PCT"), 0.0010))
    if runtime_fee is not None:
        return min(0.20, runtime_fee * 2.0 + spread_reserve), "broker_runtime_taker_fee"

    getter = getattr(strategy, "_get_broker_capabilities", None)
    if callable(getter):
        try:
            caps = getter(symbol)
            fee_method = getattr(caps, "get_round_trip_fee", None)
            if callable(fee_method):
                value = _f(fee_method(use_limit_order=False), 0.0)
                if 0.0 < value <= 0.20:
                    return value, "strategy_exchange_capabilities"
        except Exception:
            pass
    try:
        module = importlib.import_module("bot.exchange_capabilities")
        caps = module.get_broker_capabilities(_broker_name(strategy), symbol)
        value = _f(caps.get_round_trip_fee(use_limit_order=False), 0.0)
        if 0.0 < value <= 0.20:
            return value, "exchange_capability_matrix"
    except Exception:
        pass
    return max(0.004, _f(os.environ.get("NIJA_UNKNOWN_BROKER_ROUND_TRIP_COST_PCT"), 0.004)), "conservative_unknown_broker"


def _entry_side(action: str) -> str:
    return "short" if "short" in str(action or "").lower() else "long"


def _validate_live_entry(strategy: Any, df: Any, symbol: str, result: Mapping[str, Any]) -> tuple[bool, str, dict[str, Any]]:
    action = str(result.get("action") or "").strip().lower()
    if action not in {"enter_long", "enter_short", "buy", "short"}:
        return True, "not_entry", {}
    entry = _f(result.get("entry_price"))
    stop = _f(result.get("stop_loss"))
    target = _first_target(result.get("take_profit"))
    if entry <= 0.0 or stop <= 0.0 or target <= 0.0:
        return False, "entry_geometry_missing", {"entry": entry, "stop": stop, "target": target}

    validator = _validator()
    r_ok, r_reason, r_multiple = validator.validate_r_multiple(entry, stop, target)
    confirmation_ok, confirmation_reason = validator.check_first_move_confirmation(df)

    reward_pct = abs(target - entry) / entry
    risk_pct = abs(entry - stop) / entry
    cost_pct, cost_source = _round_trip_cost(strategy, symbol)
    slippage_pct = max(0.0, _f(os.environ.get("NIJA_ENTRY_SLIPPAGE_RESERVE_PCT"), 0.0015))
    minimum_net_pct = max(0.0, _f(os.environ.get("NIJA_MINIMUM_NET_PROFIT_PCT"), 0.0040))
    net_reward_pct = reward_pct - cost_pct - slippage_pct
    net_edge_ok = net_reward_pct >= minimum_net_pct

    details = {
        "entry": entry,
        "stop": stop,
        "target": target,
        "side": _entry_side(action),
        "r_multiple": r_multiple,
        "reward_pct": reward_pct,
        "risk_pct": risk_pct,
        "round_trip_cost_pct": cost_pct,
        "slippage_pct": slippage_pct,
        "net_reward_pct": net_reward_pct,
        "minimum_net_pct": minimum_net_pct,
        "confirmation": confirmation_reason,
        "cost_source": cost_source,
    }
    if not r_ok:
        return False, f"expectancy_r_multiple:{r_reason}", details
    if not confirmation_ok:
        return False, f"first_move_confirmation:{confirmation_reason}", details
    if not net_edge_ok:
        return False, "net_edge_below_fee_slippage_floor", details
    return True, "expectancy_authority_pass", details


def _patch_strategy(module: ModuleType) -> bool:
    cls = getattr(module, "NIJAApexStrategyV71", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "analyze_market", None)
    if not callable(original):
        return False
    if getattr(original, _PATCH_ATTR, False):
        return True

    @wraps(original)
    def analyze_market_with_expectancy(self: Any, df: Any, symbol: str, account_balance: float, *args: Any, **kwargs: Any):
        if _live_mode():
            # Diagnostic bypasses are useful in paper/testing but must not become
            # a live-capital entry policy.
            module._DISABLE_MARKET_FILTER = False
            module._BYPASS_SMART_FILTER = False
        result = original(self, df, symbol, account_balance, *args, **kwargs)
        if not _live_mode() or not isinstance(result, Mapping):
            return result
        ok, reason, details = _validate_live_entry(self, df, symbol, result)
        if ok:
            if reason == "expectancy_authority_pass":
                LOGGER.critical(
                    "LIVE_ENTRY_V69_EXPECTANCY_PASS marker=%s broker=%s symbol=%s action=%s "
                    "r=%.3f net_reward_pct=%.5f min_net_pct=%.5f cost_pct=%.5f cost_source=%s confirmation=%s",
                    MARKER, _broker_name(self), symbol, result.get("action"),
                    details.get("r_multiple", 0.0), details.get("net_reward_pct", 0.0),
                    details.get("minimum_net_pct", 0.0), details.get("round_trip_cost_pct", 0.0),
                    details.get("cost_source", ""), details.get("confirmation", ""),
                )
            return result

        LOGGER.warning(
            "LIVE_ENTRY_V69_BLOCKED marker=%s broker=%s symbol=%s action=%s reason=%s "
            "r=%.3f reward_pct=%.5f risk_pct=%.5f cost_pct=%.5f slippage_pct=%.5f net_reward_pct=%.5f min_net_pct=%.5f confirmation=%s",
            MARKER, _broker_name(self), symbol, result.get("action"), reason,
            details.get("r_multiple", 0.0), details.get("reward_pct", 0.0),
            details.get("risk_pct", 0.0), details.get("round_trip_cost_pct", 0.0),
            details.get("slippage_pct", 0.0), details.get("net_reward_pct", 0.0),
            details.get("minimum_net_pct", 0.0), details.get("confirmation", ""),
        )
        blocked = dict(result)
        blocked["action"] = "hold"
        blocked["reason"] = f"LIVE_ENTRY_EXPECTANCY_V69:{reason}"
        blocked["filter_stage"] = "live_entry_expectancy_v69"
        blocked["expectancy_details"] = details
        return blocked

    setattr(analyze_market_with_expectancy, _PATCH_ATTR, True)
    setattr(analyze_market_with_expectancy, "__wrapped__", original)
    cls.analyze_market = analyze_market_with_expectancy

    thresholds = getattr(cls, "_get_entry_gate_thresholds", None)
    if callable(thresholds) and not getattr(thresholds, _PATCH_ATTR, False):
        @wraps(thresholds)
        def live_thresholds(self: Any, drought: Any):
            if _live_mode():
                # Ignore only time-since-last-trade relaxation.  The normal
                # configured baseline remains authoritative.
                return thresholds(self, None)
            return thresholds(self, drought)
        setattr(live_thresholds, _PATCH_ATTR, True)
        cls._get_entry_gate_thresholds = live_thresholds

    min_score = getattr(cls, "_get_entry_gate_min_score", None)
    if callable(min_score) and not getattr(min_score, _PATCH_ATTR, False):
        @wraps(min_score)
        def live_min_score(self: Any, drought: Any):
            if _live_mode():
                baseline = int(min_score(self, None))
                configured = int(getattr(module, "ENTRY_GATE_MIN_SCORE", baseline) or baseline)
                return max(baseline, configured)
            return min_score(self, drought)
        setattr(live_min_score, _PATCH_ATTR, True)
        cls._get_entry_gate_min_score = live_min_score

    LOGGER.critical(
        "LIVE_ENTRY_EXPECTANCY_AUTHORITY_V69_PATCHED marker=%s module=%s "
        "r_min=existing_validator live_drought_relaxation=false diagnostic_bypass_live=false",
        MARKER, module.__name__,
    )
    return True


def _patch_loaded() -> bool:
    changed = False
    for name in ("bot.nija_apex_strategy_v71", "nija_apex_strategy_v71"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            changed = _patch_strategy(module) or changed
    return changed


def install_import_hook() -> bool:
    with _INSTALL_LOCK:
        _patch_loaded()
        flag = "_NIJA_LIVE_ENTRY_EXPECTANCY_AUTHORITY_V69_IMPORT_HOOK"
        if getattr(builtins, flag, False):
            return True
        original_import = builtins.__import__

        @wraps(original_import)
        def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
            result = original_import(name, globals, locals, fromlist, level)
            if "nija_apex_strategy_v71" in str(name):
                _patch_loaded()
            return result

        builtins.__import__ = guarded_import
        setattr(builtins, flag, True)
        os.environ["NIJA_LIVE_ENTRY_EXPECTANCY_AUTHORITY_V69_INSTALLED"] = "1"
        LOGGER.critical(
            "LIVE_ENTRY_EXPECTANCY_AUTHORITY_V69_INSTALLED marker=%s live_only=true",
            MARKER,
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER", "install", "install_import_hook", "_validate_live_entry", "_round_trip_cost",
]
