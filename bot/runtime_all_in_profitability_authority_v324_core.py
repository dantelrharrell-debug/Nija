"""Runtime all-in profitability authority v324.

Research-backed live-capital hardening for NIJA's economic gates.

The runtime already has strong expectancy (v69), fee-aware exit (v68), adaptive
profit trailing (v74), risk, fill, nonce and reconciliation authorities. The
remaining economic weaknesses were stale static fee data in legacy modules,
cached capability fee functions, and the absence of a conservative carrying-cost
reserve for short positions.

v324 is monotonic hardening only:
* runtime/account fee data remains authoritative whenever the broker exposes it;
* otherwise current conservative base-tier maker/taker fallbacks are used;
* v69 live entries must still clear the existing R-multiple, confirmation,
  slippage and minimum-net-profit gates after short carry when applicable;
* v68 normal profit exits include short carry in break-even/net-profit floors;
* legacy static fee consumers are updated at runtime without loosening any gate;
* short capability remains fail-closed and Alpaca equity shorts additionally
  require current borrow/locate evidence;
* protective exits, kill switch, writer/nonce authority, capital freshness,
  reconciliation and order/fill gates are untouched.

The conservative base-tier fallbacks correspond to public schedules reviewed on
2026-08-31. They are deliberately fallbacks: a proven live account tier wins.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import math
import os
import threading
from dataclasses import replace
from functools import wraps
from typing import Any, Mapping, Optional

LOGGER = logging.getLogger("nija.runtime_all_in_profitability_authority_v324")
MARKER = "20260831-runtime-all-in-profitability-authority-v324"
_PATCH_ATTR = "_nija_runtime_all_in_profitability_authority_v324"
_LOCK = threading.RLock()


def _f(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value or 0.0)
    except (TypeError, ValueError, OverflowError):
        return default
    return result if math.isfinite(result) else default


def _norm(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _is_derivative_symbol(symbol: str) -> bool:
    text = str(symbol or "").strip().upper()
    return any(token in text for token in ("PERP", "FUT", "SWAP"))


def _is_alpaca_crypto_symbol(symbol: str) -> bool:
    text = str(symbol or "").strip().upper()
    if "/" in text:
        return True
    if "-" in text and text.rsplit("-", 1)[-1] in {"USD", "USDT", "USDC", "BTC", "ETH"}:
        return True
    known = {
        "BTC", "ETH", "SOL", "DOGE", "AVAX", "LINK", "LTC", "BCH", "UNI",
        "AAVE", "DOT", "SHIB", "SUSHI", "GRT", "BAT", "MKR", "YFI", "USDT",
        "USDC",
    }
    for quote in ("USD", "USDT", "USDC", "BTC", "ETH"):
        if text.endswith(quote) and text[: -len(quote)] in known:
            return True
    return False


def _current_base_fees(broker_name: str, symbol: str) -> tuple[float, float, str]:
    """Return conservative (maker, taker, source) one-way fee fallbacks."""
    broker = _norm(broker_name)
    if broker == "kraken":
        if _is_derivative_symbol(symbol):
            return 0.0002, 0.0005, "kraken_derivatives_base_20260819"
        return 0.0040, 0.0080, "kraken_spot_tier1_20260709"
    if broker == "coinbase":
        return 0.0060, 0.0120, "coinbase_advanced_intro1_20260831"
    if broker == "okx":
        if _is_derivative_symbol(symbol):
            return 0.0002, 0.0005, "okx_futures_regular_conservative_202608"
        return 0.0008, 0.0010, "okx_spot_regular_20260814"
    if broker == "alpaca":
        if _is_alpaca_crypto_symbol(symbol):
            return 0.0015, 0.0025, "alpaca_crypto_tier1_20260831"
        return 0.0, 0.0, "alpaca_equity_commission_fallback"
    unknown = max(0.0, min(0.05, _f(os.environ.get("NIJA_UNKNOWN_BROKER_ONE_WAY_FEE_PCT"), 0.0050)))
    return unknown, unknown, "unknown_broker_conservative_fee"


def _broker_name_from_client(broker: Any) -> str:
    if broker is None:
        return "unknown"
    for attr in ("broker_name", "exchange_name", "exchange", "name"):
        value = getattr(broker, attr, None)
        text = _norm(getattr(value, "value", value))
        if text in {"kraken", "coinbase", "okx", "alpaca", "binance"}:
            return text
    broker_type = getattr(broker, "broker_type", None)
    text = _norm(getattr(broker_type, "value", broker_type))
    if text:
        for known in ("kraken", "coinbase", "okx", "alpaca", "binance"):
            if known in text:
                return known
    name = _norm(type(broker).__name__)
    for known in ("kraken", "coinbase", "okx", "alpaca", "binance"):
        if known in name:
            return known
    return "unknown"


def _strategy_broker_name(strategy: Any) -> str:
    getter = getattr(strategy, "_get_broker_name", None)
    if callable(getter):
        try:
            name = _norm(getter())
            if name:
                return name
        except Exception:
            pass
    return _broker_name_from_client(getattr(strategy, "broker_client", None))


def _extract_fee(value: Any) -> Optional[float]:
    if isinstance(value, Mapping):
        for key in ("taker_fee", "taker", "fee_rate", "trading_fee", "commission_rate", "fee"):
            if key in value:
                fee = _f(value.get(key), -1.0)
                if 0.0 <= fee <= 0.05:
                    return fee
        return None
    fee = _f(value, -1.0)
    return fee if 0.0 <= fee <= 0.05 else None


def _runtime_taker_fee(broker: Any, symbol: str) -> Optional[float]:
    if broker is None:
        return None
    for method_name in (
        "get_taker_fee", "get_fee_rate", "get_trading_fee", "get_trading_fees",
        "get_fee_schedule", "get_fees",
    ):
        method = getattr(broker, method_name, None)
        if not callable(method):
            continue
        for args, kwargs in (((symbol,), {}), ((), {"symbol": symbol}), ((), {})):
            try:
                value = method(*args, **kwargs)
            except TypeError:
                continue
            except Exception:
                break
            fee = _extract_fee(value)
            if fee is not None:
                return fee
    for attr in ("taker_fee", "taker_fee_rate", "trading_fee", "fee_rate", "commission_rate"):
        fee = _extract_fee(getattr(broker, attr, None))
        if fee is not None:
            return fee
    return None


def _all_in_round_trip_cost(strategy: Any, symbol: str) -> tuple[float, str]:
    """v69 cost source that cannot be bypassed by a cached stale capability alias."""
    broker = getattr(strategy, "broker_client", None)
    runtime_fee = _runtime_taker_fee(broker, symbol)
    spread = max(0.0, _f(os.environ.get("NIJA_ENTRY_SPREAD_RESERVE_PCT"), 0.0010))
    if runtime_fee is not None:
        return min(0.25, runtime_fee * 2.0 + spread), "broker_runtime_taker_fee_v324"
    broker_name = _strategy_broker_name(strategy)
    _maker, taker, source = _current_base_fees(broker_name, symbol)
    return min(0.25, taker * 2.0 + spread), f"current_base_fee_v324:{source}"


def _extract_short_carry(mapping: Mapping[str, Any]) -> Optional[float]:
    for key in ("short_carry_pct", "estimated_short_carry_pct", "total_short_carry_pct"):
        if key in mapping:
            value = _f(mapping.get(key), -1.0)
            if 0.0 <= value <= 0.25:
                return value
    total = 0.0
    found = False
    for key in (
        "borrow_cost_pct", "estimated_borrow_cost_pct", "margin_cost_pct",
        "estimated_margin_cost_pct", "funding_cost_pct", "estimated_funding_cost_pct",
        "regulatory_cost_pct",
    ):
        if key in mapping:
            value = _f(mapping.get(key), -1.0)
            if 0.0 <= value <= 0.25:
                total += value
                found = True
    return min(0.25, total) if found else None


def _short_carry_pct(broker: Any, symbol: str, context: Mapping[str, Any]) -> tuple[float, str]:
    direct = _extract_short_carry(context)
    metadata = context.get("metadata") if isinstance(context.get("metadata"), Mapping) else {}
    if direct is None and metadata:
        direct = _extract_short_carry(metadata)
    if direct is not None:
        return direct, "position_or_signal_metadata"

    for method_name in (
        "get_short_carry_cost_pct", "estimate_short_carry_pct", "get_borrow_cost_pct",
        "get_margin_cost_pct", "get_funding_cost_pct",
    ):
        method = getattr(broker, method_name, None) if broker is not None else None
        if not callable(method):
            continue
        for args, kwargs in (((symbol,), {}), ((), {"symbol": symbol}), ((), {})):
            try:
                value = method(*args, **kwargs)
            except TypeError:
                continue
            except Exception:
                break
            if isinstance(value, Mapping):
                cost = _extract_short_carry(value)
                if cost is None:
                    cost = _extract_fee(value)
            else:
                cost = _f(value, -1.0)
            if cost is not None and 0.0 <= float(cost) <= 0.25:
                return float(cost), f"broker_runtime:{method_name}"

    reserve = max(0.0, min(0.25, _f(os.environ.get("NIJA_SHORT_CARRY_RESERVE_PCT"), 0.0030)))
    return reserve, "conservative_short_carry_reserve"


def _asset_metadata(broker: Any, symbol: str) -> Optional[Mapping[str, Any]]:
    if broker is None:
        return None
    for name in ("get_asset", "get_asset_info", "get_symbol_info", "get_instrument_info"):
        method = getattr(broker, name, None)
        if not callable(method):
            continue
        for args, kwargs in (((symbol,), {}), ((), {"symbol": symbol})):
            try:
                value = method(*args, **kwargs)
            except TypeError:
                continue
            except Exception:
                break
            if isinstance(value, Mapping):
                return value
            if value is not None:
                result = {}
                for attr in ("asset_class", "class", "shortable", "borrow_status", "easy_to_borrow"):
                    if hasattr(value, attr):
                        result[attr] = getattr(value, attr)
                if result:
                    return result
    return None


def _short_capability(strategy: Any, symbol: str, result: Mapping[str, Any]) -> tuple[bool, str]:
    broker_name = _strategy_broker_name(strategy)
    broker = getattr(strategy, "broker_client", None)

    try:
        caps = importlib.import_module("bot.exchange_capabilities")
        can_short = getattr(caps, "can_short", None)
        if not callable(can_short) or not bool(can_short(broker_name, symbol)):
            return False, f"{broker_name}:short_capability_not_proven"
    except Exception:
        return False, f"{broker_name}:short_capability_authority_unavailable"

    if broker_name != "alpaca":
        return True, "existing_capability_authority_pass"
    if _is_alpaca_crypto_symbol(symbol):
        return False, "alpaca:crypto_shorting_unsupported"

    asset = _asset_metadata(broker, symbol)
    if not asset:
        return False, "alpaca:borrow_metadata_not_proven"
    if asset.get("shortable") is not True:
        return False, "alpaca:asset_not_proven_shortable"

    borrow_status = _norm(asset.get("borrow_status"))
    easy = asset.get("easy_to_borrow")
    if borrow_status in {"unavailable", "not_available", "no_borrow", "none"}:
        return False, f"alpaca:borrow_status={borrow_status}"
    if borrow_status in {"easy_to_borrow", "easy", "etb"} or easy is True:
        return True, "alpaca:easy_to_borrow"

    hard = borrow_status in {"hard_to_borrow", "hard", "htb"} or easy is False
    if hard:
        metadata = result.get("metadata") if isinstance(result.get("metadata"), Mapping) else {}
        locate_ok = bool(
            result.get("locate_available") or result.get("locate_id")
            or metadata.get("locate_available") or metadata.get("locate_id")
        )
        if not locate_ok:
            return False, "alpaca:hard_to_borrow_locate_not_proven"
        return True, "alpaca:hard_to_borrow_locate_proven"

    return False, "alpaca:borrow_status_not_proven"


def _patch_exchange_capabilities() -> bool:
    try:
        module = importlib.import_module("bot.exchange_capabilities")
    except Exception:
        return False
    current = getattr(module, "get_broker_capabilities", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    @wraps(current)
    def current_fee_capabilities(broker: str, symbol: str):
        caps = current(broker, symbol)
        maker, taker, source = _current_base_fees(broker, symbol)
        try:
            updated = replace(caps, maker_fee=maker, taker_fee=taker)
        except Exception:
            return caps
        try:
            setattr(updated, "_nija_fee_source", source)
        except Exception:
            pass
        return updated

    setattr(current_fee_capabilities, _PATCH_ATTR, True)
    setattr(current_fee_capabilities, "__wrapped__", current)
    module.get_broker_capabilities = current_fee_capabilities
    LOGGER.critical(
        "ALL_IN_PROFITABILITY_V324_CAPABILITY_FEES_PATCHED marker=%s current_base_fallbacks=true",
        MARKER,
    )
    return True


def _patch_legacy_fee_optimizer() -> bool:
    try:
        module = importlib.import_module("bot.broker_fee_optimizer")
        profiles = getattr(module, "BROKER_FEE_PROFILES", None)
        cls = getattr(module, "BrokerFeeProfile", None)
        if not isinstance(profiles, dict) or not isinstance(cls, type):
            return False
        for broker_name in ("kraken", "coinbase", "okx"):
            maker, taker, _source = _current_base_fees(broker_name, "BTC-USD")
            existing = profiles.get(broker_name)
            spread = float(getattr(existing, "spread_pct", 0.001) or 0.001) if existing is not None else 0.001
            profiles[broker_name] = cls(
                broker_name=broker_name,
                taker_fee_pct=taker,
                maker_fee_pct=maker,
                spread_pct=max(0.0005, spread),
            )
        LOGGER.critical(
            "ALL_IN_PROFITABILITY_V324_LEGACY_FEE_PROFILES_PATCHED marker=%s stale_kraken_coinbase_fees=false",
            MARKER,
        )
        return True
    except Exception:
        LOGGER.exception("ALL_IN_PROFITABILITY_V324_LEGACY_FEE_PATCH_FAILED marker=%s", MARKER)
        return False


def _patch_risk_sizing_fee_fallback() -> bool:
    try:
        module = importlib.import_module("bot.risk.sizing")
    except Exception:
        return False
    current = getattr(module, "_get_broker_fee", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    def current_broker_fee(broker: Any, symbol: str) -> float:
        runtime = _runtime_taker_fee(broker, symbol)
        if runtime is not None:
            return runtime
        broker_name = _broker_name_from_client(broker)
        _maker, taker, source = _current_base_fees(broker_name, symbol)
        LOGGER.debug(
            "ALL_IN_PROFITABILITY_V324_SIZING_FEE_FALLBACK marker=%s broker=%s symbol=%s fee=%.5f source=%s",
            MARKER, broker_name, symbol, taker, source,
        )
        return taker

    setattr(current_broker_fee, _PATCH_ATTR, True)
    setattr(current_broker_fee, "__wrapped__", current)
    module._get_broker_fee = current_broker_fee
    return True


def _patch_entry_authority() -> bool:
    try:
        v69 = importlib.import_module("bot.live_entry_expectancy_authority_v69_patch")
    except Exception:
        return False

    current_round_trip = getattr(v69, "_round_trip_cost", None)
    if not callable(current_round_trip):
        return False
    if not getattr(current_round_trip, _PATCH_ATTR, False):
        setattr(_all_in_round_trip_cost, _PATCH_ATTR, True)
        setattr(_all_in_round_trip_cost, "__wrapped__", current_round_trip)
        v69._round_trip_cost = _all_in_round_trip_cost

    current = getattr(v69, "_validate_live_entry", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    @wraps(current)
    def validate_all_in(strategy: Any, df: Any, symbol: str, result: Mapping[str, Any]):
        ok, reason, details = current(strategy, df, symbol, result)
        if not ok:
            return ok, reason, details
        action = _norm(result.get("action"))
        if action not in {"enter_short", "short"}:
            return ok, reason, details

        capability_ok, capability_reason = _short_capability(strategy, symbol, result)
        details = dict(details or {})
        details["short_capability"] = capability_reason
        if not capability_ok:
            return False, f"short_capability:{capability_reason}", details

        broker = getattr(strategy, "broker_client", None)
        carry, carry_source = _short_carry_pct(broker, symbol, result)
        net_before = _f(details.get("net_reward_pct"), 0.0)
        minimum_net = max(0.0, _f(details.get("minimum_net_pct"), 0.0))
        net_after = net_before - carry
        details["short_carry_pct"] = carry
        details["short_carry_source"] = carry_source
        details["net_reward_after_short_carry_pct"] = net_after
        if net_after < minimum_net:
            return False, "net_edge_below_all_in_short_cost_floor", details
        return True, "expectancy_authority_pass", details

    setattr(validate_all_in, _PATCH_ATTR, True)
    setattr(validate_all_in, "__wrapped__", current)
    v69._validate_live_entry = validate_all_in
    LOGGER.critical(
        "ALL_IN_PROFITABILITY_V324_ENTRY_PATCHED marker=%s current_fee_fallback=true "
        "cached_capability_fee_bypass=false short_carry_in_net_edge=true capability_gate_preserved=true",
        MARKER,
    )
    return True


def _patch_exit_authority() -> bool:
    try:
        v68 = importlib.import_module("bot.universal_net_profit_exit_floor_v68_patch")
    except Exception:
        return False
    current = getattr(v68, "_cost_model", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    @wraps(current)
    def all_in_cost_model(universal: Any, broker: Any, pos: Mapping[str, Any]):
        costs = dict(current(universal, broker, pos))
        try:
            short = universal.auto_exit._side(pos.get("side"), dict(pos)) in {"short", "sell"}
            symbol = universal.auto_exit._sym(pos.get("symbol"))
        except Exception:
            short = _norm(pos.get("side")) in {"short", "sell"}
            symbol = str(pos.get("symbol") or "")
        if not short:
            costs["short_carry"] = 0.0
            return costs
        carry, source = _short_carry_pct(broker, symbol, pos)
        costs["round_trip"] = min(0.25, max(0.0, _f(costs.get("round_trip"))) + carry)
        costs["short_carry"] = carry
        costs["short_carry_source"] = source
        costs["source"] = f"{costs.get('source', 'unknown')}+{source}"
        return costs

    setattr(all_in_cost_model, _PATCH_ATTR, True)
    setattr(all_in_cost_model, "__wrapped__", current)
    v68._cost_model = all_in_cost_model
    LOGGER.critical(
        "ALL_IN_PROFITABILITY_V324_EXIT_PATCHED marker=%s short_break_even_includes_carry=true protective_exits_unchanged=true",
        MARKER,
    )
    return True


def install_import_hook() -> bool:
    with _LOCK:
        outcomes = {
            "capability_fees": _patch_exchange_capabilities(),
            "legacy_fee_profiles": _patch_legacy_fee_optimizer(),
            "risk_sizing_fee_fallback": _patch_risk_sizing_fee_fallback(),
            "entry_all_in": _patch_entry_authority(),
            "exit_all_in": _patch_exit_authority(),
        }
        ready = all(outcomes.values())
        os.environ["NIJA_RUNTIME_ALL_IN_PROFITABILITY_V324_READY"] = "1" if ready else "0"
        setattr(builtins, "_NIJA_RUNTIME_ALL_IN_PROFITABILITY_AUTHORITY_V324", ready)
        if ready:
            LOGGER.critical(
                "RUNTIME_ALL_IN_PROFITABILITY_AUTHORITY_V324_READY marker=%s outcomes=%s "
                "runtime_fee_first=true current_base_fee_fallbacks=true cached_fee_bypass=false "
                "short_carry_costed=true short_borrow_proof=true short_capability_gate_preserved=true "
                "protective_exits_unchanged=true safety_gates_bypassed=false",
                MARKER, outcomes,
            )
        else:
            LOGGER.critical(
                "RUNTIME_ALL_IN_PROFITABILITY_AUTHORITY_V324_INCOMPLETE marker=%s outcomes=%s fail_closed_economic_layers_preserved=true",
                MARKER, outcomes,
            )
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_current_base_fees",
    "_all_in_round_trip_cost",
    "_short_carry_pct",
    "_short_capability",
]
