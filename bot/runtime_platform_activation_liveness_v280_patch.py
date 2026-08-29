"""Platform activation liveness recovery v280.

Production on 2026-08-29 showed the canonical MultiAccountBrokerManager shrink to
Kraken-only while process-wide Coinbase/OKX PLATFORM objects could still exist,
and showed position_sync_ready briefly report true before v146 correctly revoked
it because independent authoritative fetch proof was missing.

v280 repairs liveness only. It may adopt an existing process-wide PLATFORM
Coinbase/OKX broker into the canonical manager, reconnect that exact configured
broker through its real connect() method, synchronize the manager's normal
connection mirrors only after real connection success, wake authoritative v108
position sync, and request a normal canonical capital refresh when topology or
connectivity actually changed. It also immediately wakes v108 after v182
reasserts the fetch-proof chain instead of waiting for an unrelated future
capital refresh.

The patch never creates credentials or broker objects, never marks a failed
connect successful, never lowers broker-count/capital/notional thresholds, never
fabricates position, nonce, execution, order, acknowledgement, fill, or heartbeat
proof, never clears a kill switch or rejection window, and never forces
activation. Recovery broker I/O is bounded by a per-instance retry floor.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_platform_activation_liveness_v280")
MARKER = "20260829-platform-activation-liveness-v280"
RELEASE_ID = "20260829-runtime-convergence-v280"
_READY_FLAG = "NIJA_RUNTIME_PLATFORM_ACTIVATION_LIVENESS_V280_READY"
_PATCH_ATTR = "_nija_runtime_platform_activation_liveness_v280"
_LOCK = threading.RLock()
_SUPPORTED = ("coinbase", "okx")
_LAST_CONNECT_AT: dict[tuple[str, int], float] = {}


def _label(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip().lower()


def _connect_retry_s() -> float:
    try:
        configured = float(os.environ.get("NIJA_PLATFORM_ACTIVATION_RECOVERY_RETRY_S", "30") or 30.0)
    except (TypeError, ValueError):
        configured = 30.0
    return max(15.0, min(300.0, configured))


def _is_platform_account(broker: Any) -> bool:
    account = _label(getattr(broker, "account_type", ""))
    # Older platform adapters may not expose account_type. They are accepted only
    # when they are already held by the process-wide PLATFORM instance registry.
    return not account or account == "platform" or account.endswith(".platform")


def _canonical_manager() -> Any:
    module = importlib.import_module("bot.multi_account_broker_manager")
    getter = getattr(module, "get_broker_manager", None)
    return getter() if callable(getter) else None


def _broker_module() -> Any:
    return importlib.import_module("bot.broker_manager")


def _platform_key(manager: Any, venue: str) -> Any:
    mapping = getattr(manager, "_platform_brokers", None)
    if isinstance(mapping, dict):
        for key in mapping:
            if _label(key) == venue:
                return key
    broker_type = getattr(_broker_module(), "BrokerType", None)
    return getattr(broker_type, venue.upper(), None)


def _manager_entry(manager: Any, venue: str) -> tuple[Any, Any]:
    mapping = getattr(manager, "_platform_brokers", None)
    if not isinstance(mapping, dict):
        return None, None
    for key, broker in list(mapping.items()):
        if _label(key) == venue:
            return key, broker
    return None, None


def _global_candidate(venue: str) -> Any:
    module = _broker_module()
    instances = getattr(module, "_PLATFORM_BROKER_INSTANCES", None)
    candidate = instances.get(venue) if isinstance(instances, dict) else None
    if candidate is None or not _is_platform_account(candidate):
        return None
    return candidate


def _credentials_configured(broker: Any) -> bool:
    value = getattr(broker, "credentials_configured", None)
    if value is None:
        # Do not invent credentials. If an older adapter lacks the attribute,
        # only an already-connected object may be adopted.
        return bool(getattr(broker, "connected", False))
    return bool(value)


def _configured_by_policy(venue: str, broker: Any) -> bool:
    try:
        cfg = importlib.import_module("bot.execution_venue_config")
        if venue == "coinbase":
            fn = getattr(cfg, "should_initialize_coinbase_platform", None)
            return bool(fn(os.environ)) if callable(fn) else False
        if venue == "okx":
            fn = getattr(cfg, "should_initialize_okx_platform", None)
            return bool(fn(os.environ, credentials_configured=_credentials_configured(broker))) if callable(fn) else False
    except Exception:
        return False
    return False


def _adopt_existing(manager: Any, venue: str, broker: Any) -> bool:
    mapping = getattr(manager, "_platform_brokers", None)
    if not isinstance(mapping, dict):
        return False
    existing_key, existing = _manager_entry(manager, venue)
    if existing is broker:
        return True
    if existing is not None and existing is not broker:
        LOGGER.critical(
            "PLATFORM_ACTIVATION_V280_AMBIGUOUS marker=%s venue=%s manager_id=%s global_id=%s "
            "registry_mutated=false trading_fail_closed=true",
            MARKER, venue, id(existing), id(broker),
        )
        return False
    key = existing_key or _platform_key(manager, venue)
    if key is None:
        return False
    lock = getattr(manager, "_registry_meta_lock", None) or _LOCK
    with lock:
        mapping[key] = broker
    try:
        refresh = getattr(manager, "refresh_registry", None)
        if callable(refresh):
            refresh()
    except Exception:
        LOGGER.debug("v280 refresh_registry failed for %s", venue, exc_info=True)
    LOGGER.critical(
        "PLATFORM_ACTIVATION_V280_ADOPTED marker=%s venue=%s broker_id=%s "
        "existing_process_platform_object=true connectivity_fabricated=false credentials_fabricated=false",
        MARKER, venue, id(broker),
    )
    return True


def _connect_existing(manager: Any, venue: str, broker: Any) -> bool:
    if bool(getattr(broker, "connected", False)):
        sync = getattr(manager, "_sync_reconnect_readiness", None)
        key = _platform_key(manager, venue)
        if callable(sync) and key is not None:
            sync(key, broker)
        return True

    if not _credentials_configured(broker) or not _configured_by_policy(venue, broker):
        LOGGER.warning(
            "PLATFORM_ACTIVATION_V280_CONNECT_INELIGIBLE marker=%s venue=%s credentials=%s "
            "policy_allowed=%s trading_fail_closed=true",
            MARKER, venue, str(_credentials_configured(broker)).lower(),
            str(_configured_by_policy(venue, broker)).lower(),
        )
        return False

    attempt_key = (venue, id(broker))
    now = time.monotonic()
    with _LOCK:
        previous = float(_LAST_CONNECT_AT.get(attempt_key, 0.0) or 0.0)
        if previous > 0.0 and (now - previous) < _connect_retry_s():
            LOGGER.debug(
                "PLATFORM_ACTIVATION_V280_CONNECT_DEFERRED marker=%s venue=%s retry_in_s=%.2f "
                "duplicate_io_suppressed=true trading_fail_closed=true",
                MARKER, venue, _connect_retry_s() - (now - previous),
            )
            return False
        _LAST_CONNECT_AT[attempt_key] = now

    # Prefer the manager's normal reconnect owner when available. It calls the
    # broker's real connect() method and synchronizes readiness only on success.
    reconnect = getattr(manager, "try_reconnect_platform_broker", None)
    key = _platform_key(manager, venue)
    if callable(reconnect) and key is not None:
        try:
            return bool(reconnect(key)) and bool(getattr(broker, "connected", False))
        except Exception as exc:
            LOGGER.warning(
                "PLATFORM_ACTIVATION_V280_RECONNECT_FAILED marker=%s venue=%s error=%s:%s trading_fail_closed=true",
                MARKER, venue, type(exc).__name__, exc,
            )
            return False

    connect = getattr(broker, "connect", None)
    if not callable(connect):
        return False
    try:
        connected = bool(connect()) and bool(getattr(broker, "connected", False))
    except Exception as exc:
        LOGGER.warning(
            "PLATFORM_ACTIVATION_V280_CONNECT_FAILED marker=%s venue=%s error=%s:%s trading_fail_closed=true",
            MARKER, venue, type(exc).__name__, exc,
        )
        return False
    if not connected:
        return False
    sync = getattr(manager, "_sync_reconnect_readiness", None)
    if callable(sync) and key is not None:
        sync(key, broker)
    LOGGER.critical(
        "PLATFORM_ACTIVATION_V280_CONNECTED marker=%s venue=%s real_connect=true "
        "broker_health_unchanged=true readiness_not_fabricated=true",
        MARKER, venue,
    )
    return True


def _wake_position_sync(manager: Any, trigger: str) -> int:
    try:
        v108 = importlib.import_module("bot.platform_position_sync_v108_patch")
        dispatch = getattr(v108, "dispatch_platform_position_sync", None)
        if not callable(dispatch):
            return 0
        return int(dispatch(manager, trigger=trigger) or 0)
    except Exception:
        LOGGER.debug("v280 position wake failed", exc_info=True)
        return 0


def _request_capital_refresh(manager: Any, trigger: str) -> bool:
    refresh = getattr(manager, "refresh_capital_authority", None)
    if not callable(refresh):
        return False
    try:
        refresh(trigger=trigger)
        return True
    except Exception:
        LOGGER.debug("v280 capital refresh failed", exc_info=True)
        return False


def reconcile_once() -> dict[str, str]:
    manager = _canonical_manager()
    outcomes: dict[str, str] = {}
    if manager is None:
        return {"manager": "missing"}

    topology_changed = False
    for venue in _SUPPORTED:
        _, before = _manager_entry(manager, venue)
        candidate = _global_candidate(venue)
        if candidate is None:
            outcomes[venue] = "no_existing_platform_object"
            continue
        before_connected = bool(getattr(candidate, "connected", False))
        if not _adopt_existing(manager, venue, candidate):
            outcomes[venue] = "ownership_ambiguous"
            continue
        if before is None:
            topology_changed = True
        connected = _connect_existing(manager, venue, candidate)
        if connected:
            outcomes[venue] = "connected"
            if not before_connected:
                topology_changed = True
        else:
            outcomes[venue] = "not_connected"

    workers = _wake_position_sync(manager, "v280_platform_reconcile")
    refresh_requested = False
    if topology_changed or workers > 0:
        refresh_requested = _request_capital_refresh(manager, "v280_platform_reconcile")
    LOGGER.critical(
        "PLATFORM_ACTIVATION_V280_RECONCILE marker=%s outcomes=%s position_workers=%d "
        "topology_changed=%s capital_refresh_requested=%s duplicate_io_bounded=true "
        "thresholds_unchanged=true execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false",
        MARKER, outcomes, workers, str(topology_changed).lower(), str(refresh_requested).lower(),
    )
    return outcomes


def _patch_v182_install() -> bool:
    v182 = importlib.import_module("bot.runtime_position_fetch_proof_v182_patch")
    current = getattr(v182, "install", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def install_v280() -> bool:
        ready = bool(original())
        if not ready:
            return False
        manager = _canonical_manager()
        if manager is not None:
            workers = _wake_position_sync(manager, "v280_v182_reassert")
            LOGGER.critical(
                "POSITION_FETCH_V280_IMMEDIATE_WAKE marker=%s workers=%d "
                "authoritative_v108_only=true synthetic_success=false",
                MARKER, workers,
            )
        return True

    setattr(install_v280, _PATCH_ATTR, True)
    setattr(install_v280, "__wrapped__", original)
    v182.install = install_v280
    v182.install_import_hook = install_v280
    return True


def _register_manifest() -> bool:
    manifest = importlib.import_module("bot.runtime_release_manifest_patch")
    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    if not isinstance(required, dict):
        return False
    required["runtime_platform_activation_liveness_v280"] = _READY_FLAG
    return True


def install() -> bool:
    with _LOCK:
        try:
            v182_ok = _patch_v182_install()
            manifest_ok = _register_manifest()
            outcomes = reconcile_once()
            ready = bool(v182_ok and manifest_ok and "manager" not in outcomes)
        except Exception as exc:
            ready = False
            outcomes = {"error": f"{type(exc).__name__}:{exc}"}
            LOGGER.exception(
                "PLATFORM_ACTIVATION_LIVENESS_V280_FAILED marker=%s trading_fail_closed=true",
                MARKER,
            )
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if ready:
            LOGGER.critical(
                "PLATFORM_ACTIVATION_LIVENESS_V280_READY marker=%s ready=true outcomes=%s "
                "existing_platform_objects_only=true real_connect_required=true authoritative_position_fetch_required=true "
                "capital_thresholds_unchanged=true freshness_extended=false kill_switch_unchanged=true "
                "execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false",
                MARKER, outcomes,
            )
        return ready


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER", "RELEASE_ID", "install", "install_import_hook", "reconcile_once",
    "_global_candidate", "_adopt_existing", "_connect_existing", "_wake_position_sync",
    "_patch_v182_install", "_connect_retry_s",
]
