"""Broker-independent readiness guard for NIJA live entries.

A brokerage can block only orders routed to itself. Coinbase or OKX being
unavailable must never stop Kraken (or another healthy broker) from scanning,
sizing, exiting, or executing. Legacy environment names remain for telemetry.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any, Mapping

logger = logging.getLogger("nija.secondary_venue_strict_readiness")

_MARKER = "20260711i"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_KNOWN = {"coinbase", "okx", "kraken", "alpaca", "binance"}
_LOCK = threading.RLock()
_INSTALLED = False
_MONITOR_STARTED = False
_LAST_SIGNATURE = ""
_PIPELINE_WRAP_ATTR = "_nija_broker_independent_readiness_v20260711i"
_STRATEGY_WRAP_ATTR = "_nija_broker_independent_entry_v20260711i"
_PATCHED_PIPELINE: set[str] = set()
_PATCHED_STRATEGY: set[str] = set()


def _truthy(name: str, default: str = "") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in _TRUE


def strict_mode_enabled() -> bool:
    """Legacy flag, now interpreted as a broker-local activation check."""
    return _truthy("NIJA_REQUIRE_SECONDARY_VENUES_READY", "false")


def required_venues() -> list[str]:
    raw = os.environ.get("NIJA_REQUIRED_LIVE_VENUES", "coinbase,okx") or "coinbase,okx"
    result: list[str] = []
    for item in raw.split(","):
        name = str(item or "").strip().lower()
        if name in _KNOWN and name not in result:
            result.append(name)
    return result


def _normalise_name(value: Any) -> str:
    raw = getattr(value, "value", value)
    text = str(raw or "").strip().lower()
    compact = text.replace("_", "").replace("-", "").replace(" ", "")
    for name in _KNOWN:
        if name in compact:
            return name
    return text


def _broker_name(broker: Any, fallback: Any = "") -> str:
    if isinstance(broker, (str, bytes)):
        return _normalise_name(broker) or _normalise_name(fallback) or "unknown"
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


def _connected_state(broker: Any) -> tuple[bool, bool]:
    if broker is None:
        return False, False
    for attr in ("connected", "is_connected"):
        try:
            if not hasattr(broker, attr):
                continue
            value = getattr(broker, attr)
            value = value() if callable(value) else value
            if value is not None:
                return bool(value), True
        except Exception:
            return False, True
    for attr in ("connection_state", "_connection_state", "status"):
        try:
            if not hasattr(broker, attr):
                continue
            value = getattr(broker, attr, None)
            text = str(getattr(value, "value", value) or "").strip().lower()
            if text in {"connected", "ready", "active", "online"}:
                return True, True
            if text in {"disconnected", "failed", "offline", "closed", "not_started"}:
                return False, True
        except Exception:
            return False, True
    return False, False


def _broker_connected(broker: Any) -> bool:
    return _connected_state(broker)[0]


def _runtime_brokers() -> dict[str, Any]:
    brokers: dict[str, Any] = {}

    def add(raw_key: Any, broker: Any) -> None:
        if broker is None or isinstance(broker, bool):
            return
        name = _broker_name(broker, raw_key)
        if name in _KNOWN:
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
        for attr in ("_platform_brokers", "platform_brokers", "brokers"):
            mapping = getattr(manager, attr, None) if manager is not None else None
            if isinstance(mapping, Mapping):
                for raw_key, broker in mapping.items():
                    add(raw_key, broker)

    for module_name in ("bot.broker_manager", "broker_manager"):
        module = sys.modules.get(module_name)
        if not isinstance(module, ModuleType):
            continue
        for attr in ("_PLATFORM_BROKER_INSTANCES", "GLOBAL_PLATFORM_BROKERS"):
            mapping = getattr(module, attr, None)
            if isinstance(mapping, Mapping):
                for raw_key, broker in mapping.items():
                    add(raw_key, broker)
    return brokers


def _venue_status(name: str, brokers: dict[str, Any] | None = None) -> dict[str, Any]:
    name = _normalise_name(name)
    key = name.upper()
    broker = (brokers if brokers is not None else _runtime_brokers()).get(name)
    connected, connection_observed = _connected_state(broker)
    connected_env = f"NIJA_{key}_CONNECTED"
    if broker is None and connected_env in os.environ:
        connected, connection_observed = _truthy(connected_env), True

    activation_env = f"NIJA_{key}_ACTIVATION_STATE"
    trading_env = f"NIJA_{key}_TRADING_READY"
    activated_env = f"NIJA_{key}_ACTIVATED"
    spendable_env = f"NIJA_{key}_SPENDABLE_QUOTE"
    activation = str(os.environ.get(activation_env, "unknown") or "unknown").strip().lower()
    trading_ready = _truthy(trading_env)
    activated = _truthy(activated_env)
    activation_observed = any(
        env in os.environ for env in (activation_env, trading_env, activated_env, spendable_env)
    )
    try:
        spendable = max(0.0, float(os.environ.get(spendable_env, "0") or "0"))
    except (TypeError, ValueError):
        spendable = 0.0

    local_strict = strict_mode_enabled() and name in set(required_venues())
    known = broker is not None or connection_observed or activation_observed
    if local_strict:
        ready = connected and trading_ready and activated and activation == "ready"
        if not connected:
            reason = "not_connected"
        elif activation != "ready":
            reason = f"activation_state:{activation}"
        elif not trading_ready:
            reason = "trading_ready_flag_false"
        elif not activated:
            reason = "activated_flag_false"
        else:
            reason = "ready"
    else:
        ready = connected
        reason = "ready" if ready else ("not_connected" if known else "not_registered")

    return {
        "venue": name,
        "ready": ready,
        "known": known,
        "connected": connected,
        "broker_local_strict": local_strict,
        "activation_state": activation,
        "trading_ready": trading_ready,
        "activated": activated,
        "spendable_quote": round(spendable, 8),
        "reason": reason,
    }


def refresh_readiness(*, force_log: bool = False) -> tuple[bool, list[str], dict[str, dict[str, Any]]]:
    """Publish per-broker status; never create an all-brokers entry block."""
    global _LAST_SIGNATURE
    brokers = _runtime_brokers()
    names: list[str] = []
    for name in [*required_venues(), *brokers.keys()]:
        name = _normalise_name(name)
        if name in _KNOWN and name not in names:
            names.append(name)
    statuses = {name: _venue_status(name, brokers) for name in names}
    monitored = set(required_venues())
    missing = [name for name in names if name in monitored and not statuses[name]["ready"]]
    active = [name for name in names if statuses[name]["ready"]]
    degraded = [name for name in names if statuses[name]["known"] and not statuses[name]["ready"]]

    os.environ["NIJA_REQUIRED_VENUES_READY"] = "1"
    os.environ["NIJA_MULTI_BROKER_TRADING_READY"] = "1" if active else "0"
    os.environ["NIJA_REQUIRED_VENUES_MISSING"] = ",".join(missing)
    os.environ["NIJA_ACTIVE_LIVE_VENUES"] = ",".join(active)
    os.environ["NIJA_DEGRADED_LIVE_VENUES"] = ",".join(degraded)
    os.environ["NIJA_REQUIRED_VENUES_STATUS_JSON"] = json.dumps(statuses, sort_keys=True, separators=(",", ":"))
    os.environ.pop("NIJA_NEW_ENTRY_BLOCK_REASON", None)

    signature = json.dumps(
        {"mode": "broker_independent", "active": active, "degraded": degraded, "missing": missing, "statuses": statuses},
        sort_keys=True,
        separators=(",", ":"),
    )
    if force_log or signature != _LAST_SIGNATURE:
        _LAST_SIGNATURE = signature
        log = logger.warning if degraded or missing else logger.info
        log(
            "BROKER_INDEPENDENT_READINESS marker=%s active=%s degraded=%s missing_monitored=%s status=%s",
            _MARKER,
            ",".join(active) or "none",
            ",".join(degraded) or "none",
            ",".join(missing) or "none",
            signature,
        )
    return True, missing, statuses


def required_venues_ready() -> bool:
    return refresh_readiness()[0]


def _is_entry_request(request: Any) -> bool:
    if bool(getattr(request, "reduce_only", False)):
        return False
    intent = str(getattr(request, "intent_type", "entry") or "entry").strip().lower()
    effect = str(getattr(request, "position_effect", "") or "").strip().lower()
    return intent not in {"exit", "reduce", "close", "liquidate", "liquidation"} and effect not in {"close", "reduce", "exit"}


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


def _request_target(request: Any, pipeline: Any) -> tuple[str, Any]:
    request_attrs = ("preferred_broker", "broker", "broker_client", "execution_broker", "broker_name", "venue", "exchange")
    pipeline_attrs = ("broker", "broker_client", "execution_broker", "venue", "exchange")
    for owner, attrs in ((request, request_attrs), (pipeline, pipeline_attrs)):
        for attr in attrs:
            try:
                value = getattr(owner, attr, None)
            except Exception:
                continue
            if value is None:
                continue
            name = _broker_name(value, value)
            if name in _KNOWN:
                broker = value if not isinstance(value, (str, bytes)) else _runtime_brokers().get(name)
                return name, broker
    return "", None


def _patch_execution_pipeline(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionPipeline", None)
    current = getattr(cls, "execute", None) if isinstance(cls, type) else None
    if not callable(current):
        return False
    if getattr(current, _PIPELINE_WRAP_ATTR, False):
        _PATCHED_PIPELINE.add(getattr(module, "__name__", "<unknown>"))
        return True
    original = current

    def _independent_execute(self: Any, request: Any) -> Any:
        if strict_mode_enabled() and _is_entry_request(request):
            target_name, target_broker = _request_target(request, self)
            if target_name in set(required_venues()):
                status = _venue_status(target_name, {target_name: target_broker} if target_broker is not None else None)
                if not status["ready"]:
                    started = time.monotonic()
                    reason = f"target_broker_not_ready:{target_name}:{status['reason']}"
                    logger.warning(
                        "BROKER_LOCAL_ENTRY_BLOCKED marker=%s broker=%s symbol=%s side=%s reason=%s status=%s",
                        _MARKER,
                        target_name,
                        getattr(request, "symbol", ""),
                        getattr(request, "side", ""),
                        reason,
                        json.dumps(status, sort_keys=True, separators=(",", ":")),
                    )
                    return _pipeline_denial(module, request, reason, started)
        return original(self, request)

    setattr(_independent_execute, _PIPELINE_WRAP_ATTR, True)
    setattr(_independent_execute, "__wrapped__", original)
    setattr(cls, "execute", _independent_execute)
    name = getattr(module, "__name__", "<unknown>")
    _PATCHED_PIPELINE.add(name)
    logger.warning("BROKER_INDEPENDENT_PIPELINE_PATCHED marker=%s module=%s", _MARKER, name)
    return True


def _patch_trading_strategy(module: ModuleType) -> bool:
    cls = getattr(module, "TradingStrategy", None)
    current = getattr(cls, "_is_broker_eligible_for_entry", None) if isinstance(cls, type) else None
    if not callable(current):
        return False
    if getattr(current, _STRATEGY_WRAP_ATTR, False):
        _PATCHED_STRATEGY.add(getattr(module, "__name__", "<unknown>"))
        return True
    original = current

    def _independent_eligibility(self: Any, broker: Any) -> tuple[bool, str]:
        allowed, reason = original(self, broker)
        if not allowed or not strict_mode_enabled():
            return allowed, reason
        name = _broker_name(broker)
        if name not in set(required_venues()):
            return allowed, reason
        status = _venue_status(name, {name: broker})
        if status["ready"]:
            return allowed, reason
        local_reason = f"target broker {name} not ready: {status['reason']}"
        logger.warning(
            "BROKER_LOCAL_ENTRY_ELIGIBILITY_BLOCKED marker=%s broker=%s reason=%s status=%s",
            _MARKER,
            name,
            local_reason,
            json.dumps(status, sort_keys=True, separators=(",", ":")),
        )
        return False, local_reason

    setattr(_independent_eligibility, _STRATEGY_WRAP_ATTR, True)
    setattr(_independent_eligibility, "__wrapped__", original)
    setattr(cls, "_is_broker_eligible_for_entry", _independent_eligibility)
    name = getattr(module, "__name__", "<unknown>")
    _PATCHED_STRATEGY.add(name)
    logger.warning("BROKER_INDEPENDENT_STRATEGY_PATCHED marker=%s module=%s", _MARKER, name)
    return True


def _patch_loaded() -> tuple[bool, bool]:
    pipeline = strategy = False
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
            logger.exception("BROKER_INDEPENDENT_READINESS_MONITOR_ERROR marker=%s", _MARKER)
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
            threading.Thread(target=_monitor, name="broker-independent-readiness", daemon=True).start()
        os.environ["NIJA_SECONDARY_VENUE_STRICT_GUARD_INSTALLED"] = "1"
        os.environ["NIJA_BROKER_INDEPENDENT_READINESS_INSTALLED"] = "1"
        logger.warning(
            "BROKER_INDEPENDENT_READINESS_INSTALLED marker=%s broker_local_strict=%s monitored=%s",
            _MARKER,
            strict_mode_enabled(),
            ",".join(required_venues()),
        )
        print(
            f"[NIJA-PRINT] BROKER_INDEPENDENT_READINESS_INSTALLED marker={_MARKER} "
            f"broker_local_strict={str(strict_mode_enabled()).lower()} monitored={','.join(required_venues())}",
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
