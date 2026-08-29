"""Heartbeat position-cap venue failover for genuine startup proof (v273).

Production on 2026-08-29 proved the startup heartbeat reached Coinbase through
all canonical writer/nonce/lifecycle gates but the local execution hardening
layer rejected the verification BUY because that account was already above its
tier position-count cap. That local pre-dispatch denial is valid for Coinbase,
but it must not permanently deadlock execution proof when another venue already
published by NIJA's canonical execution-readiness set can run the same probe.

v273 does not bypass the position cap. It observes the unchanged ECEL result
only inside the already-authorized HEARTBEAT_TRADE ContextVar, temporarily
quarantines the position-cap-blocked venue for heartbeat selection, and retries
on another already-ready venue. Ordinary orders, account tier limits, ECEL,
risk, capital, writer/nonce authority, kill switch, broker health, minimum
notional, exchange acknowledgement, fill confirmation, and activation remain
unchanged. No failed/local validation is treated as execution proof.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any, Callable

LOGGER = logging.getLogger("nija.runtime_heartbeat_position_cap_failover_v273")
MARKER = "20260829-heartbeat-position-cap-failover-v273"
RELEASE_ID = "20260829-runtime-convergence-v273"
_READY_FLAG = "NIJA_HEARTBEAT_POSITION_CAP_FAILOVER_V273_READY"
_HARDENING_PATCH_ATTR = "_nija_heartbeat_position_cap_failover_v273_hardening"
_STRATEGY_PATCH_ATTR = "_nija_heartbeat_position_cap_failover_v273_strategy"
_LOCK = threading.RLock()
_TLS = threading.local()
_ALLOWED_REASON = "HEARTBEAT_TRADE"


def _quarantine_s() -> float:
    try:
        configured = float(os.environ.get("NIJA_HEARTBEAT_POSITION_CAP_QUARANTINE_S", "60") or 60.0)
    except (TypeError, ValueError):
        configured = 60.0
    return max(15.0, min(300.0, configured))


def _max_fallbacks() -> int:
    try:
        configured = int(float(os.environ.get("NIJA_HEARTBEAT_POSITION_CAP_MAX_FALLBACKS", "2") or 2))
    except (TypeError, ValueError):
        configured = 2
    return max(1, min(3, configured))


def _clear_cap_block() -> None:
    _TLS.cap_block = None


def _set_cap_block(reason: str, *, symbol: str = "", side: str = "") -> None:
    _TLS.cap_block = {
        "reason": str(reason or ""),
        "symbol": str(symbol or ""),
        "side": str(side or ""),
        "at": time.monotonic(),
    }


def _recent_cap_block(max_age_s: float = 3.0) -> dict[str, Any] | None:
    value = getattr(_TLS, "cap_block", None)
    if not isinstance(value, dict):
        return None
    try:
        age = time.monotonic() - float(value.get("at", 0.0) or 0.0)
    except Exception:
        return None
    if age < 0.0 or age > max_age_s:
        return None
    reason = str(value.get("reason", "") or "")
    upper = reason.upper()
    if "POSITION_CAP_EXCEEDED" not in upper and "POSITION CAP REACHED" not in upper:
        return None
    return dict(value)


def _trusted_heartbeat_probe() -> tuple[bool, str]:
    if threading.current_thread().name != "HeartbeatTrade":
        return False, "not_heartbeat_thread"
    try:
        v263 = importlib.import_module("bot.runtime_heartbeat_state_machine_gate_v263_patch")
        verifier = getattr(v263, "_verified_startup_probe", None)
        if not callable(verifier):
            return False, "v263_verifier_unavailable"
        ok, detail = verifier()
        reason = str(detail or "").strip().upper()
        if not bool(ok) or reason != _ALLOWED_REASON:
            return False, reason or "startup_probe_not_verified"
        return True, reason
    except Exception as exc:
        return False, f"startup_probe_verification_error:{type(exc).__name__}:{exc}"


def _broker_key(strategy: Any, broker: Any) -> str:
    try:
        v255 = importlib.import_module("bot.runtime_terminal_activation_liveness_v255_patch")
        resolver = getattr(v255, "_broker_key", None)
        if callable(resolver):
            value = str(resolver(strategy, broker) or "").strip().lower()
            if value:
                return value
    except Exception:
        pass
    resolver = getattr(strategy, "_broker_key_from_obj", None)
    if callable(resolver):
        try:
            value = str(resolver(broker) or "").strip().lower()
            if value:
                return value
        except Exception:
            pass
    broker_type = str(getattr(broker, "broker_type", "") or "").strip().lower()
    if broker_type:
        return broker_type
    name = type(broker).__name__.replace("Broker", "").strip().lower()
    return name or "unknown"


def _active_quarantine(strategy: Any, attr: str) -> dict[str, float]:
    now = time.monotonic()
    current = getattr(strategy, attr, None)
    raw = dict(current) if isinstance(current, dict) else {}
    active: dict[str, float] = {}
    for name, expiry in raw.items():
        try:
            expiry_value = float(expiry or 0.0)
        except Exception:
            continue
        if expiry_value > now:
            active[str(name).strip().lower()] = expiry_value
    setattr(strategy, attr, active)
    return active


def _quarantine_cap_venue(strategy: Any, broker: Any, detail: str) -> str:
    venue = _broker_key(strategy, broker)
    active = _active_quarantine(strategy, "_nija_heartbeat_position_cap_until")
    active[venue] = time.monotonic() + _quarantine_s()
    setattr(strategy, "_nija_heartbeat_position_cap_until", active)
    LOGGER.warning(
        "HEARTBEAT_POSITION_CAP_V273_QUARANTINED marker=%s venue=%s ttl_s=%.1f detail=%s "
        "position_cap_unchanged=true broker_health_unchanged=true rejection_window_unchanged=true "
        "execution_proof_fabricated=false trading_fail_closed=true",
        MARKER, venue, _quarantine_s(), detail,
    )
    return venue


def _ready_venue_filter(strategy: Any) -> tuple[str | None, tuple[str, ...], tuple[str, ...]]:
    if "NIJA_EXECUTION_READY_VENUES" not in os.environ:
        return None, (), ()
    raw = str(os.environ.get("NIJA_EXECUTION_READY_VENUES", "") or "")
    ready = tuple(dict.fromkeys(part.strip().lower() for part in raw.split(",") if part.strip()))
    cap = _active_quarantine(strategy, "_nija_heartbeat_position_cap_until")
    local = _active_quarantine(strategy, "_nija_heartbeat_local_busy_until")
    blocked_set = set(cap) | set(local)
    blocked = tuple(sorted(name for name in ready if name in blocked_set))
    allowed = tuple(name for name in ready if name not in blocked_set)
    return raw, allowed, blocked


def _candidate_brokers(strategy: Any) -> dict[Any, Any]:
    candidates: dict[Any, Any] = {}
    manager = getattr(strategy, "multi_account_manager", None)
    if manager is not None:
        try:
            candidates.update(getattr(manager, "platform_brokers", {}) or {})
        except Exception as exc:
            LOGGER.debug("Heartbeat v273 MABM lookup failed: %s", exc)
    broker_manager = getattr(strategy, "broker_manager", None)
    if broker_manager is not None:
        try:
            candidates.update(getattr(broker_manager, "brokers", {}) or {})
            primary = broker_manager.get_primary_broker()
            if primary is not None:
                candidates.setdefault(getattr(primary, "broker_type", "primary"), primary)
        except Exception as exc:
            LOGGER.debug("Heartbeat v273 BrokerManager lookup failed: %s", exc)
    broker = getattr(strategy, "broker", None)
    if broker is not None:
        candidates.setdefault(getattr(broker, "broker_type", "cached"), broker)
    return candidates


def _wrap_hardening(current: Callable[..., Any]) -> Callable[..., Any]:
    if bool(getattr(current, _HARDENING_PATCH_ATTR, False)):
        return current

    @wraps(current)
    def validate_v273(self: Any, *args: Any, **kwargs: Any):
        result = current(self, *args, **kwargs)
        try:
            is_valid = bool(result[0]) if isinstance(result, tuple) and result else bool(result)
            detail = str(result[1] or "") if isinstance(result, tuple) and len(result) > 1 else ""
            if is_valid:
                return result
            upper = detail.upper()
            if "POSITION_CAP_EXCEEDED" not in upper and "POSITION CAP REACHED" not in upper:
                return result
            trusted, probe_reason = _trusted_heartbeat_probe()
            if not trusted or probe_reason != _ALLOWED_REASON:
                return result
            symbol = str(kwargs.get("symbol", args[0] if len(args) > 0 else "") or "")
            side = str(kwargs.get("side", args[1] if len(args) > 1 else "") or "")
            if side.strip().upper() not in {"BUY", "ENTER", "OPEN"}:
                return result
            _set_cap_block(detail, symbol=symbol, side=side)
            LOGGER.info(
                "HEARTBEAT_POSITION_CAP_V273_OBSERVED marker=%s symbol=%s side=%s probe_reason=%s "
                "ecel_result_unchanged=true order_not_submitted=true position_cap_unchanged=true",
                MARKER, symbol, side, probe_reason,
            )
        except Exception as exc:
            LOGGER.debug("Heartbeat v273 hardening observation failed: %s", exc)
        return result

    setattr(validate_v273, _HARDENING_PATCH_ATTR, True)
    setattr(validate_v273, "__wrapped__", current)
    return validate_v273


def _patch_hardening() -> tuple[bool, tuple[str, ...]]:
    try:
        importlib.import_module("bot.execution_layer_hardening")
    except Exception as exc:
        LOGGER.warning("HEARTBEAT_POSITION_CAP_V273_HARDENING_IMPORT_DEFERRED marker=%s error=%s:%s", MARKER, type(exc).__name__, exc)
    patched: list[str] = []
    seen: set[int] = set()
    for name in ("bot.execution_layer_hardening", "execution_layer_hardening"):
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            continue
        cls = getattr(module, "ExecutionLayerHardening", None)
        if not isinstance(cls, type) or id(cls) in seen:
            continue
        seen.add(id(cls))
        current = getattr(cls, "validate_order_hardening", None)
        if not callable(current):
            continue
        wrapped = _wrap_hardening(current)
        setattr(cls, "validate_order_hardening", wrapped)
        if bool(getattr(getattr(cls, "validate_order_hardening", None), _HARDENING_PATCH_ATTR, False)):
            patched.append(str(getattr(module, "__name__", name)))
    return bool(patched), tuple(sorted(set(patched)))


def _wrap_selector(current: Callable[..., Any]) -> Callable[..., Any]:
    if bool(getattr(current, _STRATEGY_PATCH_ATTR, False)):
        return current

    @wraps(current)
    def select_v273(self: Any):
        raw, allowed, blocked = _ready_venue_filter(self)
        cap_blocked = set(_active_quarantine(self, "_nija_heartbeat_position_cap_until"))
        if raw is None or not cap_blocked:
            return current(self)
        if not allowed:
            LOGGER.warning("HEARTBEAT_POSITION_CAP_V273_NO_READY_FALLBACK marker=%s blocked=%s canonical_ready_set_only=true retry_later=true trading_fail_closed=true", MARKER, ",".join(blocked))
            return None
        allowed_set = set(allowed)
        candidates = {raw_key: broker for raw_key, broker in _candidate_brokers(self).items() if broker is not None and _broker_key(self, broker) in allowed_set}
        selector = getattr(self, "_select_entry_broker", None)
        if not callable(selector):
            LOGGER.error("HEARTBEAT_POSITION_CAP_V273_SELECTOR_MISSING marker=%s trading_fail_closed=true", MARKER)
            return None
        selected, _name, status = selector(candidates)
        if selected is None or _broker_key(self, selected) not in allowed_set:
            LOGGER.warning("HEARTBEAT_POSITION_CAP_V273_FAILOVER_UNAVAILABLE marker=%s allowed=%s blocked=%s status=%s trading_fail_closed=true", MARKER, ",".join(allowed), ",".join(blocked), status or "no_matching_broker_objects")
            return None
        self.broker = selected
        broker_manager = getattr(self, "broker_manager", None)
        if broker_manager is not None:
            try:
                broker_manager.active_broker = selected
            except Exception:
                pass
        LOGGER.critical("HEARTBEAT_POSITION_CAP_V273_FAILOVER marker=%s blocked=%s selected=%s canonical_ready_set_only=true position_cap_unchanged=true ordinary_routing_unchanged=true broker_health_unchanged=true execution_proof_fabricated=false", MARKER, ",".join(blocked), _broker_key(self, selected))
        return selected

    setattr(select_v273, _STRATEGY_PATCH_ATTR, True)
    setattr(select_v273, "__wrapped__", current)
    return select_v273


def _wrap_execute(current: Callable[..., Any]) -> Callable[..., Any]:
    if bool(getattr(current, _STRATEGY_PATCH_ATTR, False)):
        return current

    @wraps(current)
    def execute_v273(self: Any) -> bool:
        fallbacks = 0
        while True:
            _clear_cap_block()
            if bool(current(self)):
                return True
            block = _recent_cap_block()
            if block is None:
                return False
            broker = getattr(self, "broker", None)
            if broker is None:
                LOGGER.warning("HEARTBEAT_POSITION_CAP_V273_BROKER_UNKNOWN marker=%s trading_fail_closed=true", MARKER)
                return False
            failed_venue = _quarantine_cap_venue(self, broker, str(block.get("reason", "")))
            fallbacks += 1
            if fallbacks > _max_fallbacks():
                LOGGER.warning("HEARTBEAT_POSITION_CAP_V273_FALLBACK_LIMIT marker=%s failed_venue=%s fallbacks=%d max_fallbacks=%d retry_later=true trading_fail_closed=true", MARKER, failed_venue, fallbacks - 1, _max_fallbacks())
                return False
            _raw, allowed, blocked = _ready_venue_filter(self)
            if not allowed:
                LOGGER.warning("HEARTBEAT_POSITION_CAP_V273_ALL_READY_VENUES_BLOCKED marker=%s failed_venue=%s blocked=%s retry_later=true trading_fail_closed=true", MARKER, failed_venue, ",".join(blocked))
                return False
            LOGGER.critical("HEARTBEAT_POSITION_CAP_V273_IMMEDIATE_RETRY marker=%s failed_venue=%s fallback=%d max_fallbacks=%d allowed=%s position_cap_unchanged=true ordinary_orders_unchanged=true safety_gates_unchanged=true", MARKER, failed_venue, fallbacks, _max_fallbacks(), ",".join(allowed))

    setattr(execute_v273, _STRATEGY_PATCH_ATTR, True)
    setattr(execute_v273, "__wrapped__", current)
    return execute_v273


def _patch_trading_strategy() -> tuple[bool, tuple[str, ...]]:
    try:
        importlib.import_module("bot.trading_strategy")
    except Exception as exc:
        LOGGER.warning("HEARTBEAT_POSITION_CAP_V273_STRATEGY_IMPORT_DEFERRED marker=%s error=%s:%s", MARKER, type(exc).__name__, exc)
    patched: list[str] = []
    seen: set[int] = set()
    for name in ("bot.trading_strategy", "trading_strategy"):
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            continue
        cls = getattr(module, "TradingStrategy", None)
        if not isinstance(cls, type) or id(cls) in seen:
            continue
        seen.add(id(cls))
        selector = getattr(cls, "_get_heartbeat_broker", None)
        execute = getattr(cls, "_execute_heartbeat_trade", None)
        if not callable(selector) or not callable(execute):
            continue
        cls._get_heartbeat_broker = _wrap_selector(selector)
        cls._execute_heartbeat_trade = _wrap_execute(execute)
        if all(bool(getattr(getattr(cls, method, None), _STRATEGY_PATCH_ATTR, False)) for method in ("_get_heartbeat_broker", "_execute_heartbeat_trade")):
            patched.append(str(getattr(module, "__name__", name)))
    return bool(patched), tuple(sorted(set(patched)))


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["heartbeat_position_cap_failover_v273"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        try:
            hardening_ready, hardening_surfaces = _patch_hardening()
            strategy_ready, strategy_surfaces = _patch_trading_strategy()
            manifest_ready = _register_manifest()
            ready = bool(hardening_ready and strategy_ready and manifest_ready)
        except Exception as exc:
            LOGGER.error("HEARTBEAT_POSITION_CAP_V273_INSTALL_ERROR marker=%s error=%s:%s trading_fail_closed=true", MARKER, type(exc).__name__, exc, exc_info=True)
            ready, hardening_surfaces, strategy_surfaces, manifest_ready = False, (), (), False
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if ready:
            LOGGER.critical("HEARTBEAT_POSITION_CAP_FAILOVER_V273_READY marker=%s ready=true hardening_surfaces=%s strategy_surfaces=%s canonical_ready_set_only=true trusted_heartbeat_context_only=true position_cap_unchanged=true ecel_result_unchanged=true ordinary_orders_unchanged=true writer_nonce_risk_capital_killswitch_broker_health_min_notional_order_fill_gates_unchanged=true execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false", MARKER, ",".join(hardening_surfaces), ",".join(strategy_surfaces))
        return ready


def install_import_hook() -> bool:
    return install()


__all__ = ["MARKER", "RELEASE_ID", "install", "install_import_hook", "_trusted_heartbeat_probe", "_recent_cap_block", "_quarantine_cap_venue", "_ready_venue_filter", "_wrap_hardening", "_wrap_selector", "_wrap_execute", "_patch_hardening", "_patch_trading_strategy"]
