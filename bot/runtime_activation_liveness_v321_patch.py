"""Activation liveness convergence v321.

Production generation 5056 exposed two fail-closed liveness gaps after v320:

* v285 correctly revokes strong position proof when a connected PLATFORM
  snapshot ages past its 90-second TTL, but later installer churn can restore
  v108's historical adoption-latch discovery.  An already-adopted broker can
  then remain stale without being redispatched for a real authoritative read.
* the heartbeat selector can repeatedly choose a canonically ready venue whose
  v210 authenticated read is already in flight.  The heartbeat fails before it
  can reach another ready venue, leaving genuine execution proof stale even
  though another canonical venue is available.

v321 repairs only those liveness paths.  It never creates readiness, positions,
balances, execution proof, or order/fill success:

* v108 discovery is reasserted to v285's strong platform candidate function, so
  stale/missing authoritative platform snapshots are redispatched through the
  existing startup adopter and all existing snapshot/cost-basis/protection
  checks remain authoritative;
* only on the dedicated HeartbeatTrade thread, a broker with a currently-live
  v210 authenticated-read flight may be skipped in favor of another broker that
  is already present in NIJA_EXECUTION_READY_VENUES.  If no alternate exists,
  heartbeat selection fails closed instead of launching a duplicate private
  read.

Ordinary order routing is unchanged.  Writer, nonce, capital, risk, kill-switch,
ECEL, minimum-notional, acknowledgement, fill, position TTL and protective-exit
requirements are unchanged.  No forced activation or synthetic success is
permitted.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
from functools import wraps
from typing import Any, Callable

LOGGER = logging.getLogger("nija.runtime_activation_liveness_v321")
MARKER = "20260831-activation-liveness-v321"
RELEASE_ID = "20260831-runtime-convergence-v321"
_READY_FLAG = "NIJA_RUNTIME_ACTIVATION_LIVENESS_V321_READY"
_PATCH_ATTR = "_nija_runtime_activation_liveness_v321"
_LOCK = threading.RLock()


def _chain_has_exact(callable_obj: Any, expected_name: str | None = None) -> bool:
    seen: set[int] = set()
    current = callable_obj
    for _ in range(96):
        if not callable(current) or id(current) in seen:
            return False
        seen.add(id(current))
        owner = getattr(current, "__globals__", {}) or {}
        if bool(getattr(current, _PATCH_ATTR, False)) and owner.get("MARKER") == MARKER:
            if expected_name is None or str(getattr(current, "__name__", "")) == expected_name:
                return True
        current = getattr(current, "__wrapped__", None)
    return False


def _strong_platform_candidates(manager: Any) -> list[tuple[str, Any]]:
    """Return only v285-identified PLATFORM brokers missing current strong proof."""
    try:
        v285 = importlib.import_module("bot.runtime_authoritative_position_coverage_v285_patch")
        resolver = getattr(v285, "_platform_candidates", None)
        if not callable(resolver):
            return []
        return list(resolver(manager) or [])
    except Exception as exc:
        LOGGER.warning(
            "ACTIVATION_LIVENESS_V321_PLATFORM_DISCOVERY_DEFERRED marker=%s error=%s:%s "
            "trading_fail_closed=true synthetic_success=false",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return []


def _patch_v108_discovery() -> bool:
    try:
        v108 = importlib.import_module("bot.platform_position_sync_v108_patch")
    except Exception:
        return False
    current = getattr(v108, "_connected_unsynced_platform_brokers", None)
    if not callable(current):
        return False
    if _chain_has_exact(current, "discovery_v321"):
        return True
    original = current

    @wraps(original)
    def discovery_v321(manager: Any) -> list[tuple[str, Any]]:
        return _strong_platform_candidates(manager)

    discovery_v321.__name__ = "discovery_v321"
    setattr(discovery_v321, _PATCH_ATTR, True)
    setattr(discovery_v321, "__wrapped__", original)
    v108._connected_unsynced_platform_brokers = discovery_v321
    return True


def _wrap_reassertor(module: Any, attr: str) -> bool:
    """Reapply strong discovery after v182/v285 installer replay changes v108."""
    current = getattr(module, attr, None)
    if not callable(current):
        return False
    if _chain_has_exact(current, f"{attr}_v321"):
        return True
    original = current

    @wraps(original)
    def reassert_v321(*args: Any, **kwargs: Any):
        result = original(*args, **kwargs)
        strong = _patch_v108_discovery()
        if not strong:
            LOGGER.critical(
                "ACTIVATION_LIVENESS_V321_DISCOVERY_REASSERT_FAILED marker=%s source=%s "
                "trading_fail_closed=true readiness_fabricated=false",
                MARKER,
                attr,
            )
        return result

    reassert_v321.__name__ = f"{attr}_v321"
    setattr(reassert_v321, _PATCH_ATTR, True)
    setattr(reassert_v321, "__wrapped__", original)
    setattr(module, attr, reassert_v321)
    return True


def _patch_position_reassertors() -> bool:
    try:
        v182 = importlib.import_module("bot.runtime_position_fetch_proof_v182_patch")
        v285 = importlib.import_module("bot.runtime_authoritative_position_coverage_v285_patch")
    except Exception:
        return False
    return bool(
        _patch_v108_discovery()
        and _wrap_reassertor(v182, "_patch_discovery")
        and _wrap_reassertor(v285, "_patch_v182_discovery")
    )


def _broker_label(strategy: Any, broker: Any) -> str:
    resolver = getattr(strategy, "_broker_key_from_obj", None)
    if callable(resolver):
        try:
            value = str(resolver(broker) or "").strip().lower()
            if value:
                return value
        except Exception:
            pass
    raw = getattr(broker, "broker_type", "")
    raw = getattr(raw, "value", raw)
    value = str(raw or "").strip().lower()
    if value:
        return value.rsplit(".", 1)[-1]
    return type(broker).__name__.replace("Broker", "").strip().lower() or "unknown"


def _candidate_brokers(strategy: Any) -> dict[Any, Any]:
    candidates: dict[Any, Any] = {}
    manager = getattr(strategy, "multi_account_manager", None)
    if manager is not None:
        for attr in ("platform_brokers", "_platform_brokers"):
            mapping = getattr(manager, attr, None)
            if callable(mapping):
                try:
                    mapping = mapping()
                except Exception:
                    mapping = None
            if isinstance(mapping, dict):
                candidates.update(mapping)
    broker_manager = getattr(strategy, "broker_manager", None)
    if broker_manager is not None:
        mapping = getattr(broker_manager, "brokers", None)
        if isinstance(mapping, dict):
            candidates.update(mapping)
        getter = getattr(broker_manager, "get_primary_broker", None)
        if callable(getter):
            try:
                primary = getter()
            except Exception:
                primary = None
            if primary is not None:
                candidates.setdefault(getattr(primary, "broker_type", "primary"), primary)
    cached = getattr(strategy, "broker", None)
    if cached is not None:
        candidates.setdefault(getattr(cached, "broker_type", "cached"), cached)
    return candidates


def _canonical_ready_venues() -> set[str]:
    if "NIJA_EXECUTION_READY_VENUES" not in os.environ:
        return set()
    return {
        part.strip().lower()
        for part in str(os.environ.get("NIJA_EXECUTION_READY_VENUES", "") or "").split(",")
        if part.strip()
    }


def _broker_auth_busy(broker: Any) -> tuple[bool, str]:
    """Observe v210 single-flight state without creating or retiring any flight."""
    try:
        v210 = importlib.import_module("bot.runtime_heartbeat_auth_probe_bound_v210_patch")
    except Exception:
        return False, "v210_unavailable"
    flights = getattr(v210, "_FLIGHTS", None)
    lock = getattr(v210, "_LOCK", None)
    methods = tuple(getattr(v210, "_AUTH_READ_METHODS", ()) or ())
    if not isinstance(flights, dict) or lock is None:
        return False, "v210_state_unavailable"

    def _inspect() -> tuple[bool, str]:
        for method in methods:
            worker = flights.get((id(broker), str(method)))
            alive = getattr(worker, "is_alive", None) if worker is not None else None
            try:
                if callable(alive) and bool(alive()):
                    return True, str(method)
            except Exception:
                continue
        return False, "none"

    try:
        with lock:
            return _inspect()
    except Exception:
        return _inspect()


def _wrap_heartbeat_selector(current: Callable[..., Any]) -> Callable[..., Any]:
    if _chain_has_exact(current, "heartbeat_selector_v321"):
        return current

    @wraps(current)
    def heartbeat_selector_v321(self: Any):
        selected = current(self)
        if selected is None or not threading.current_thread().name.startswith("HeartbeatTrade"):
            return selected
        busy, busy_method = _broker_auth_busy(selected)
        if not busy:
            return selected

        ready = _canonical_ready_venues()
        if not ready:
            LOGGER.warning(
                "HEARTBEAT_AUTH_BUSY_V321_NO_CANONICAL_ALTERNATE marker=%s selected=%s method=%s "
                "reason=canonical_ready_set_empty duplicate_private_read=false trading_fail_closed=true",
                MARKER,
                _broker_label(self, selected),
                busy_method,
            )
            return None

        alternatives = {
            raw_key: broker
            for raw_key, broker in _candidate_brokers(self).items()
            if broker is not None
            and broker is not selected
            and _broker_label(self, broker) in ready
            and not _broker_auth_busy(broker)[0]
        }
        selector = getattr(self, "_select_entry_broker", None)
        if not alternatives or not callable(selector):
            LOGGER.warning(
                "HEARTBEAT_AUTH_BUSY_V321_NO_ALTERNATE marker=%s selected=%s method=%s ready_venues=%s "
                "duplicate_private_read=false trading_fail_closed=true",
                MARKER,
                _broker_label(self, selected),
                busy_method,
                ",".join(sorted(ready)),
            )
            return None

        try:
            fallback, name, status = selector(alternatives)
        except Exception as exc:
            LOGGER.warning(
                "HEARTBEAT_AUTH_BUSY_V321_SELECTOR_ERROR marker=%s selected=%s error=%s:%s "
                "duplicate_private_read=false trading_fail_closed=true",
                MARKER,
                _broker_label(self, selected),
                type(exc).__name__,
                exc,
            )
            return None
        if fallback is None or _broker_label(self, fallback) not in ready:
            LOGGER.warning(
                "HEARTBEAT_AUTH_BUSY_V321_ALTERNATE_UNAVAILABLE marker=%s selected=%s status=%s "
                "duplicate_private_read=false trading_fail_closed=true",
                MARKER,
                _broker_label(self, selected),
                status or "no_alternate",
            )
            return None

        self.broker = fallback
        broker_manager = getattr(self, "broker_manager", None)
        if broker_manager is not None:
            try:
                broker_manager.active_broker = fallback
            except Exception:
                pass
        LOGGER.critical(
            "HEARTBEAT_AUTH_BUSY_FAILOVER_V321 marker=%s skipped=%s busy_method=%s selected=%s "
            "canonical_ready_venues=%s heartbeat_thread_only=true selection_only=true "
            "duplicate_private_read=false execution_readiness_not_granted=true "
            "execution_proof_fabricated=false forced_activation=false ordinary_orders_unchanged=true "
            "writer_nonce_risk_capital_killswitch_ecel_min_notional_order_fill_gates_unchanged=true "
            "safety_gates_bypassed=false",
            MARKER,
            _broker_label(self, selected),
            busy_method,
            str(name or _broker_label(self, fallback)).lower(),
            ",".join(sorted(ready)),
        )
        return fallback

    heartbeat_selector_v321.__name__ = "heartbeat_selector_v321"
    setattr(heartbeat_selector_v321, _PATCH_ATTR, True)
    setattr(heartbeat_selector_v321, "__wrapped__", current)
    return heartbeat_selector_v321


def _patch_loaded_strategy() -> bool:
    patched = False
    seen: set[int] = set()
    for name in ("bot.trading_strategy", "trading_strategy"):
        module = sys.modules.get(name)
        cls = getattr(module, "TradingStrategy", None) if module is not None else None
        if not isinstance(cls, type) or id(cls) in seen:
            continue
        seen.add(id(cls))
        current = getattr(cls, "_get_heartbeat_broker", None)
        if not callable(current):
            continue
        cls._get_heartbeat_broker = _wrap_heartbeat_selector(current)
        patched = _chain_has_exact(getattr(cls, "_get_heartbeat_broker", None), "heartbeat_selector_v321") or patched
    return patched


def _patch_v274_factory() -> bool:
    try:
        v274 = importlib.import_module("bot.runtime_heartbeat_live_venue_selection_v274_patch")
    except Exception:
        return False
    current = getattr(v274, "_wrap_selector", None)
    if not callable(current):
        return False
    if not _chain_has_exact(current, "wrap_selector_factory_v321"):
        original = current

        @wraps(original)
        def wrap_selector_factory_v321(base: Callable[..., Any]) -> Callable[..., Any]:
            return _wrap_heartbeat_selector(original(base))

        wrap_selector_factory_v321.__name__ = "wrap_selector_factory_v321"
        setattr(wrap_selector_factory_v321, _PATCH_ATTR, True)
        setattr(wrap_selector_factory_v321, "__wrapped__", original)
        v274._wrap_selector = wrap_selector_factory_v321
    _patch_loaded_strategy()
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_activation_liveness_v321"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        position_ready = _patch_position_reassertors()
        heartbeat_ready = _patch_v274_factory()
        manifest_ready = _register_manifest()
        ready = bool(position_ready and heartbeat_ready and manifest_ready)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "RUNTIME_ACTIVATION_LIVENESS_V321_NOT_READY marker=%s position_ready=%s heartbeat_ready=%s "
                "manifest_ready=%s trading_fail_closed=true readiness_fabricated=false "
                "execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false",
                MARKER,
                str(position_ready).lower(),
                str(heartbeat_ready).lower(),
                str(manifest_ready).lower(),
            )
            return False
        LOGGER.critical(
            "RUNTIME_ACTIVATION_LIVENESS_V321_READY marker=%s ready=true "
            "v285_strong_platform_refresh_reasserted=true stale_snapshot_redispatch=true "
            "heartbeat_v210_busy_failover=true canonical_ready_venues_only=true "
            "heartbeat_thread_only=true duplicate_private_read=false ordinary_orders_unchanged=true "
            "position_snapshot_ttl_unchanged=true readiness_fabricated=false execution_proof_fabricated=false "
            "forced_activation=false writer_nonce_risk_capital_killswitch_ecel_min_notional_order_fill_gates_unchanged=true "
            "safety_gates_bypassed=false",
            MARKER,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_strong_platform_candidates",
    "_patch_v108_discovery",
    "_patch_position_reassertors",
    "_broker_auth_busy",
    "_canonical_ready_venues",
    "_candidate_brokers",
    "_wrap_heartbeat_selector",
    "_patch_v274_factory",
]
