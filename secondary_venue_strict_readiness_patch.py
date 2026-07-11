"""Strict Coinbase/OKX readiness guard for NIJA live entries.

This module makes secondary-venue readiness an explicit production invariant.
It never creates credentials, fabricates balances, changes broker permissions,
places probe orders, or bypasses existing risk controls.  When strict mode is
enabled, only *new entries* are blocked until every required venue is connected
and has reached the supervised activation state ``ready``.  Exits, reductions,
and emergency liquidation paths remain permitted.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any, Mapping, Optional

logger = logging.getLogger("nija.secondary_venue_strict_readiness")

_MARKER = "20260710ah"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_LOCK = threading.RLock()
_INSTALLED = False
_MONITOR_STARTED = False
_LAST_SIGNATURE = ""
_PIPELINE_WRAP_ATTR = "_nija_required_secondary_venues_v20260710ah"
_STRATEGY_WRAP_ATTR = "_nija_required_secondary_venues_entry_v20260710ah"
_PATCHED_PIPELINE: set[str] = set()
_PATCHED_STRATEGY: set[str] = set()


def _truthy(name: str, default: str = "") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in _TRUE


def strict_mode_enabled() -> bool:
    return _truthy("NIJA_REQUIRE_SECONDARY_VENUES_READY", "false")


def required_venues() -> list[str]:
    raw = os.environ.get("NIJA_REQUIRED_LIVE_VENUES", "coinbase,okx") or "coinbase,okx"
    venues: list[str] = []
    for item in raw.split(","):
        name = str(item or "").strip().lower()
        if name in {"coinbase", "okx"} and name not in venues:
            venues.append(name)
    return venues


def _normalise_name(value: Any) -> str:
    raw = getattr(value, "value", value)
    text = str(raw or "").strip().lower()
    compact = text.replace("_", "").replace("-", "").replace(" ", "")
    for key in ("coinbase", "okx", "kraken", "alpaca", "binance"):
        if key in compact:
            return key
    return text


def _broker_name(broker: Any, fallback: Any = "") -> str:
    if broker is not None:
        for attr in ("broker_type", "name", "broker_name", "exchange", "exchange_name", "NAME"):
            try:
                name = _normalise_name(getattr(broker, attr, None))
                if name:
                    return name
            except Exception:
                pass
        try:
            name = _normalise_name(type(broker).__name__)
            if name:
                return name
        except Exception:
            pass
    return _normalise_name(fallback) or "unknown"


def _broker_connected(broker: Any) -> bool:
    if broker is None:
        return False
    observed = False
    for attr in ("connected", "is_connected"):
        try:
            if not hasattr(broker, attr):
                continue
            observed = True
            value = getattr(broker, attr)
            value = value() if callable(value) else value
            if value is None:
                continue
            if not bool(value):
                return False
        except Exception:
            return False
    if observed:
        return True
    for attr in ("connection_state", "_connection_state", "status"):
        try:
            raw = getattr(getattr(broker, attr, None), "value", getattr(broker, attr, None))
            text = str(raw or "").strip().lower()
            if text in {"connected", "ready", "active", "online"}:
                return True
            if text in {"disconnected", "failed", "offline", "closed", "not_started"}:
                return False
        except Exception:
            pass
    return False


def _runtime_brokers() -> dict[str, Any]:
    brokers: dict[str, Any] = {}

    def add(raw_key: Any, broker: Any) -> None:
        if broker is None:
            return
        name = _broker_name(broker, raw_key)
        if name in {"coinbase", "okx", "kraken", "alpaca", "binance"}:
            brokers[name] = broker

    for module_name in ("bot.multi_account_broker_manager", "multi_account_broker_manager"):
        module = sys.modules.get(module_name)
        if not isinstance(module, ModuleType):
            continue
        manager = getattr(module, "multi_account_broker_manager", None)
        if manager is None:
            getter = getattr(module, "get_broker_manager", None)
            try:
                manager = getter() if callable(getter) else None
            except Exception:
                manager = None
        if manager is None:
            continue
        for attr in ("_platform_brokers", "platform_brokers", "brokers"):
            try:
                mapping = getattr(manager, attr, None)
                if isinstance(mapping, Mapping):
                    for raw_key, broker in mapping.items():
                        add(raw_key, broker)
            except Exception:
                pass

    for module_name in ("bot.broker_manager", "broker_manager"):
        module = sys.modules.get(module_name)
        if not isinstance(module, ModuleType):
            continue
        for attr in ("_PLATFORM_BROKER_INSTANCES", "GLOBAL_PLATFORM_BROKERS"):
            try:
                mapping = getattr(module, attr, None)
                if isinstance(mapping, Mapping):
                    for raw_key, broker in mapping.items():
                        if isinstance(broker, bool):
                            continue
                        add(raw_key, broker)
            except Exception:
                pass
    return brokers


def _venue_status(name: str, brokers: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    key = name.upper()
    brokers = brokers if brokers is not None else _runtime_brokers()
    broker = brokers.get(name)
    connected = _broker_connected(broker)
    activation_state = str(os.environ.get(f"NIJA_{key}_ACTIVATION_STATE", "unknown") or "unknown").strip().lower()
    trading_ready = _truthy(f"NIJA_{key}_TRADING_READY")
    activated = _truthy(f"NIJA_{key}_ACTIVATED")
    spendable_raw = str(os.environ.get(f"NIJA_{key}_SPENDABLE_QUOTE", "0") or "0")
    try:
        spendable = max(0.0, float(spendable_raw))
    except (TypeError, ValueError):
        spendable = 0.0
    ready = connected and trading_ready and activated and activation_state == "ready"
    reason = "ready"
    if not connected:
        reason = "not_connected"
    elif activation_state != "ready":
        reason = f"activation_state:{activation_state}"
    elif not trading_ready:
        reason = "trading_ready_flag_false"
    elif not activated:
        reason = "activated_flag_false"
    return {
        "venue": name,
        "ready": ready,
        "connected": connected,
        "activation_state": activation_state,
        "trading_ready": trading_ready,
        "activated": activated,
        "spendable_quote": round(spendable, 8),
        "reason": reason,
    }


def refresh_readiness(*, force_log: bool = False) -> tuple[bool, list[str], dict[str, dict[str, Any]]]:
    global _LAST_SIGNATURE
    names = required_venues()
    strict = strict_mode_enabled()
    brokers = _runtime_brokers()
    statuses = {name: _venue_status(name, brokers) for name in names}
    missing = [name for name in names if not statuses[name]["ready"]]
    ready = (not strict) or not missing

    os.environ["NIJA_REQUIRED_VENUES_READY"] = "1" if ready else "0"
    os.environ["NIJA_MULTI_BROKER_TRADING_READY"] = "1" if ready else "0"
    os.environ["NIJA_REQUIRED_VENUES_MISSING"] = ",".join(missing)
    os.environ["NIJA_REQUIRED_VENUES_STATUS_JSON"] = json.dumps(statuses, sort_keys=True, separators=(",", ":"))
    if ready:
        os.environ.pop("NIJA_NEW_ENTRY_BLOCK_REASON", None)
    else:
        os.environ["NIJA_NEW_ENTRY_BLOCK_REASON"] = "required_secondary_venues_not_ready:" + ",".join(missing)

    signature = json.dumps(
        {"strict": strict, "ready": ready, "missing": missing, "statuses": statuses},
        sort_keys=True,
        separators=(",", ":"),
    )
    if force_log or signature != _LAST_SIGNATURE:
        _LAST_SIGNATURE = signature
        if ready:
            logger.critical(
                "REQUIRED_SECONDARY_VENUES_READY marker=%s strict=%s venues=%s status=%s",
                _MARKER,
                strict,
                ",".join(names) or "none",
                signature,
            )
        else:
            logger.critical(
                "REQUIRED_SECONDARY_VENUES_BLOCKED marker=%s strict=%s missing=%s status=%s",
                _MARKER,
                strict,
                ",".join(missing) or "none",
                signature,
            )
    return ready, missing, statuses


def required_venues_ready() -> bool:
    ready, _missing, _statuses = refresh_readiness()
    return ready


def _is_entry_request(request: Any) -> bool:
    if bool(getattr(request, "reduce_only", False)):
        return False
    intent = str(getattr(request, "intent_type", "entry") or "entry").strip().lower()
    position_effect = str(getattr(request, "position_effect", "") or "").strip().lower()
    if intent in {"exit", "reduce", "close", "liquidate", "liquidation"}:
        return False
    if position_effect in {"close", "reduce", "exit"}:
        return False
    return True


def _pipeline_denial(module: ModuleType, request: Any, reason: str, started: float) -> Any:
    result_cls = getattr(module, "PipelineResult", None)
    if callable(result_cls):
        return result_cls(
            success=False,
            symbol=str(getattr(request, "symbol", "") or ""),
            side=str(getattr(request, "side", "") or ""),
            size_usd=float(getattr(request, "size_usd", 0.0) or 0.0),
            error=reason,
            latency_ms=(time.monotonic() - started) * 1000.0,
        )
    raise RuntimeError(reason)


def _patch_execution_pipeline(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionPipeline", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "execute", None)
    if not callable(current):
        return False
    if getattr(current, _PIPELINE_WRAP_ATTR, False):
        _PATCHED_PIPELINE.add(getattr(module, "__name__", "<unknown>"))
        return True
    original = current

    def _strict_execute(self: Any, request: Any) -> Any:
        if strict_mode_enabled() and _is_entry_request(request):
            ready, missing, statuses = refresh_readiness()
            if not ready:
                started = time.monotonic()
                reason = "required_secondary_venues_not_ready:" + ",".join(missing)
                logger.critical(
                    "REQUIRED_SECONDARY_VENUES_ENTRY_BLOCKED marker=%s surface=execution_pipeline "
                    "symbol=%s side=%s missing=%s status=%s",
                    _MARKER,
                    getattr(request, "symbol", ""),
                    getattr(request, "side", ""),
                    ",".join(missing),
                    json.dumps(statuses, sort_keys=True, separators=(",", ":")),
                )
                return _pipeline_denial(module, request, reason, started)
        return original(self, request)

    setattr(_strict_execute, _PIPELINE_WRAP_ATTR, True)
    setattr(_strict_execute, "__wrapped__", original)
    setattr(cls, "execute", _strict_execute)
    name = getattr(module, "__name__", "<unknown>")
    _PATCHED_PIPELINE.add(name)
    logger.warning("REQUIRED_SECONDARY_VENUES_PIPELINE_PATCHED marker=%s module=%s", _MARKER, name)
    return True


def _patch_trading_strategy(module: ModuleType) -> bool:
    cls = getattr(module, "TradingStrategy", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "_is_broker_eligible_for_entry", None)
    if not callable(current):
        return False
    if getattr(current, _STRATEGY_WRAP_ATTR, False):
        _PATCHED_STRATEGY.add(getattr(module, "__name__", "<unknown>"))
        return True
    original = current

    def _strict_eligibility(self: Any, broker: Any) -> tuple[bool, str]:
        if strict_mode_enabled():
            ready, missing, _statuses = refresh_readiness()
            if not ready:
                reason = "required secondary venues not ready: " + ",".join(missing)
                logger.warning(
                    "REQUIRED_SECONDARY_VENUES_ENTRY_ELIGIBILITY_BLOCKED marker=%s broker=%s missing=%s",
                    _MARKER,
                    _broker_name(broker),
                    ",".join(missing),
                )
                return False, reason
        return original(self, broker)

    setattr(_strict_eligibility, _STRATEGY_WRAP_ATTR, True)
    setattr(_strict_eligibility, "__wrapped__", original)
    setattr(cls, "_is_broker_eligible_for_entry", _strict_eligibility)
    name = getattr(module, "__name__", "<unknown>")
    _PATCHED_STRATEGY.add(name)
    logger.warning("REQUIRED_SECONDARY_VENUES_STRATEGY_PATCHED marker=%s module=%s", _MARKER, name)
    return True


def _patch_loaded() -> tuple[bool, bool]:
    pipeline = False
    strategy = False
    for name in ("bot.execution_pipeline", "execution_pipeline"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            pipeline = _patch_execution_pipeline(module) or pipeline
    for name in ("bot.trading_strategy", "trading_strategy"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            strategy = _patch_trading_strategy(module) or strategy
    return pipeline, strategy


def _monitor() -> None:
    while True:
        try:
            refresh_readiness()
            _patch_loaded()
        except Exception:
            logger.exception("REQUIRED_SECONDARY_VENUES_MONITOR_ERROR marker=%s", _MARKER)
        try:
            interval = max(1.0, float(os.environ.get("NIJA_SECONDARY_VENUE_STRICT_RECHECK_S", "2") or "2"))
        except (TypeError, ValueError):
            interval = 2.0
        time.sleep(interval)


def install() -> None:
    global _INSTALLED, _MONITOR_STARTED
    with _LOCK:
        if _INSTALLED:
            refresh_readiness()
            _patch_loaded()
            return
        _INSTALLED = True
        refresh_readiness(force_log=True)
        _patch_loaded()
        if not _MONITOR_STARTED:
            _MONITOR_STARTED = True
            thread = threading.Thread(
                target=_monitor,
                name="secondary-venue-strict-readiness",
                daemon=True,
            )
            thread.start()
        os.environ["NIJA_SECONDARY_VENUE_STRICT_GUARD_INSTALLED"] = "1"
        logger.warning(
            "SECONDARY_VENUE_STRICT_READINESS_INSTALLED marker=%s strict=%s required=%s",
            _MARKER,
            strict_mode_enabled(),
            ",".join(required_venues()),
        )
        print(
            f"[NIJA-PRINT] SECONDARY_VENUE_STRICT_READINESS_INSTALLED marker={_MARKER} "
            f"strict={str(strict_mode_enabled()).lower()} required={','.join(required_venues())}",
            flush=True,
        )


__all__ = [
    "install",
    "strict_mode_enabled",
    "required_venues",
    "refresh_readiness",
    "required_venues_ready",
    "_patch_execution_pipeline",
    "_patch_trading_strategy",
]
