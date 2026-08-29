"""Recover missing configured Coinbase/OKX platform broker objects (v284).

Production on 2026-08-29 exposed a liveness gap after v283 deployment: the
canonical MultiAccountBrokerManager could retain Kraken while configured
Coinbase/OKX had no canonical or process-wide PLATFORM object. v280 can adopt
and reconnect an existing object, but deliberately never creates one. The
canonical platform initializer is one-shot, so a missing object after that
point can otherwise remain absent indefinitely and keep capital/position/
execution proof fail closed.

v284 repairs only that missing-object seam. Once broker registration has
finished, it may construct the exact CoinbaseBroker/OKXBroker class used by the
canonical initializer, and only when policy enables the venue, required
platform credential *presence* is proven from the environment, and neither the
canonical manager nor process-wide platform registry already has an object.

The object is published disconnected/NOT_STARTED. Credential-presence metadata
is set true only after those exact environment variables are proven present;
this does not authenticate them. v284 then delegates the real bounded reconnect
to v280. v280 still requires broker.connect() to return success and
broker.connected to become true before connectivity is accepted. Failed auth,
network, balance, position or readiness proof remains failed closed.

Safety contract
---------------
* No credential values are logged, invented, rewritten, or authenticated here.
* No connectivity, balance, capital, position, nonce, execution, order,
  acknowledgement, fill, heartbeat, or activation truth is fabricated.
* Existing writer, nonce, risk, kill-switch, broker-health, ECEL,
  minimum-notional, order and fill gates remain authoritative.
* User broker objects are never candidates and are never modified.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from typing import Any

LOGGER = logging.getLogger("nija.runtime_platform_object_liveness_v284")
MARKER = "20260829-platform-object-liveness-v284"
RELEASE_ID = "20260829-runtime-convergence-v284"
_READY_FLAG = "NIJA_RUNTIME_PLATFORM_OBJECT_LIVENESS_V284_READY"
_LOCK = threading.RLock()
_SUPPORTED = ("coinbase", "okx")
_LAST_LOG_SIGNATURE = ""


def _label(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip().lower()


def _canonical_manager() -> Any:
    try:
        module = importlib.import_module("bot.multi_account_broker_manager")
        getter = getattr(module, "get_broker_manager", None)
        return getter() if callable(getter) else None
    except Exception:
        return None


def _broker_module() -> Any:
    try:
        return importlib.import_module("bot.broker_manager")
    except Exception:
        return None


def _venue_config_module() -> Any:
    try:
        return importlib.import_module("bot.execution_venue_config")
    except Exception:
        return None


def _registration_finalized(manager: Any) -> bool:
    event = getattr(manager, "_broker_registration_complete", None)
    is_set = getattr(event, "is_set", None)
    if callable(is_set):
        try:
            return bool(is_set())
        except Exception:
            return False
    return False


def _platform_init_busy(manager: Any) -> bool:
    lock = getattr(manager, "_platform_init_lock", None)
    locked = getattr(lock, "locked", None)
    if callable(locked):
        try:
            return bool(locked())
        except Exception:
            return True
    return False


def _manager_entry(manager: Any, venue: str) -> tuple[Any, Any]:
    mapping = getattr(manager, "_platform_brokers", None)
    if not isinstance(mapping, dict):
        return None, None
    for key, broker in list(mapping.items()):
        if _label(key) == venue:
            return key, broker
    return None, None


def _global_candidate(broker_module: Any, venue: str) -> Any:
    instances = getattr(broker_module, "_PLATFORM_BROKER_INSTANCES", None)
    return instances.get(venue) if isinstance(instances, dict) else None


def _credential_proof(venue: str) -> bool:
    if venue == "coinbase":
        key = str(os.environ.get("COINBASE_API_KEY", "") or "").strip()
        secret = str(
            os.environ.get("COINBASE_API_SECRET", "")
            or os.environ.get("COINBASE_PEM_CONTENT", "")
            or ""
        ).strip()
        return bool(key and secret)
    if venue == "okx":
        key = str(os.environ.get("OKX_API_KEY", "") or "").strip()
        secret = str(os.environ.get("OKX_API_SECRET", "") or "").strip()
        passphrase = str(
            os.environ.get("OKX_API_PASSPHRASE", "")
            or os.environ.get("OKX_PASSPHRASE", "")
            or ""
        ).strip()
        return bool(key and secret and passphrase)
    return False


def _policy_allows(venue: str) -> bool:
    config = _venue_config_module()
    if config is None:
        return False
    try:
        if venue == "coinbase":
            fn = getattr(config, "should_initialize_coinbase_platform", None)
            return bool(fn(os.environ)) if callable(fn) else False
        if venue == "okx":
            fn = getattr(config, "should_initialize_okx_platform", None)
            return bool(fn(os.environ, credentials_configured=_credential_proof(venue))) if callable(fn) else False
    except Exception:
        return False
    return False


def _configured_and_allowed(venue: str) -> bool:
    return bool(_credential_proof(venue) and _policy_allows(venue))


def _broker_type_for(broker_module: Any, venue: str) -> Any:
    broker_type = getattr(broker_module, "BrokerType", None)
    value = getattr(broker_type, venue.upper(), None)
    return value if _label(value) == venue else None


def _construct_platform_broker(broker_module: Any, venue: str) -> Any:
    if not _credential_proof(venue):
        raise RuntimeError(f"{venue}_credential_presence_unproven")
    class_name = {"coinbase": "CoinbaseBroker", "okx": "OKXBroker"}.get(venue)
    broker_cls = getattr(broker_module, class_name, None) if class_name else None
    if not isinstance(broker_cls, type):
        raise RuntimeError(f"{venue}_broker_class_missing")
    broker = broker_cls()
    account = _label(getattr(broker, "account_type", ""))
    if account and account != "platform" and not account.endswith(".platform"):
        raise RuntimeError(f"{venue}_constructor_not_platform:{account}")
    # BaseBroker.credentials_configured means credential material was supplied,
    # not that authentication succeeded. Normal Coinbase/OKX connect() paths set
    # this after reading the same environment variables. Set it here only after
    # exact presence proof so v280 may attempt the real connect; success is still
    # accepted only from broker.connect() + broker.connected.
    if hasattr(broker, "credentials_configured"):
        setattr(broker, "credentials_configured", True)
    return broker


def _publish_missing_object(manager: Any, broker_module: Any, venue: str, broker: Any) -> str:
    broker_type = _broker_type_for(broker_module, venue)
    if broker_type is None:
        raise RuntimeError(f"{venue}_broker_type_missing")

    registry_lock = getattr(broker_module, "_PLATFORM_BROKER_REGISTRY_LOCK", None) or _LOCK
    manager_lock = getattr(manager, "_registry_meta_lock", None) or _LOCK

    with manager_lock:
        _, manager_existing = _manager_entry(manager, venue)
        if manager_existing is not None:
            return "manager_present_race"
        with registry_lock:
            if _global_candidate(broker_module, venue) is not None:
                return "global_present_race"

            mapping = getattr(manager, "_platform_brokers", None)
            instances = getattr(broker_module, "_PLATFORM_BROKER_INSTANCES", None)
            presence = getattr(broker_module, "GLOBAL_PLATFORM_BROKERS", None)
            connected = getattr(broker_module, "_PLATFORM_BROKER_CONNECTED", None)
            if not isinstance(mapping, dict) or not isinstance(instances, dict):
                raise RuntimeError(f"{venue}_registry_unavailable")

            mapping[broker_type] = broker
            instances[venue] = broker
            if isinstance(presence, dict):
                presence[venue] = True
            if isinstance(connected, dict):
                connected[venue] = False

            local_connected = getattr(manager, "_platform_connected", None)
            if isinstance(local_connected, dict):
                local_connected[venue] = False

            state_map = getattr(manager, "_platform_state", None)
            try:
                mabm = importlib.import_module("bot.multi_account_broker_manager")
                connection_state = getattr(mabm, "ConnectionState", None)
                not_started = getattr(connection_state, "NOT_STARTED", None)
            except Exception:
                not_started = None
            if isinstance(state_map, dict) and not_started is not None:
                state_map[venue] = not_started

    record = getattr(manager, "_record_broker_registration", None)
    if callable(record):
        record(broker_type, broker)
    event_getter = getattr(manager, "_get_or_create_platform_event", None)
    if callable(event_getter):
        event_getter(broker_type)

    payload_map = getattr(manager, "_broker_payload_fsm", None)
    if isinstance(payload_map, dict) and broker_type not in payload_map:
        try:
            capital_fsm = importlib.import_module("bot.capital_flow_state_machine")
            payload_cls = getattr(capital_fsm, "BrokerPayloadFSM", None)
            if isinstance(payload_cls, type):
                payload_map[broker_type] = payload_cls(broker_id=venue)
        except Exception:
            LOGGER.debug("v284 payload FSM creation failed for %s", venue, exc_info=True)

    try:
        mabm = importlib.import_module("bot.multi_account_broker_manager")
        registry = getattr(mabm, "broker_registry", None)
        if registry is not None:
            registry[venue]["platform"] = True
    except Exception:
        LOGGER.debug("v284 broker_registry mirror failed for %s", venue, exc_info=True)

    LOGGER.critical(
        "PLATFORM_OBJECT_V284_REGISTERED marker=%s venue=%s broker_id=%s "
        "late_recovery_registration=true credential_presence_proven=true authenticated=false "
        "connected=false broker_io=false balance_fetch=false position_fetch=false "
        "execution_authority_unchanged=true",
        MARKER,
        venue,
        id(broker),
    )
    return "registered_missing_object"


def reconcile_once() -> dict[str, str]:
    manager = _canonical_manager()
    broker_module = _broker_module()
    if manager is None or broker_module is None:
        return {"__runtime__": "manager_or_broker_module_missing"}

    if not _registration_finalized(manager):
        return {venue: "registration_in_progress" for venue in _SUPPORTED}
    if _platform_init_busy(manager):
        return {venue: "platform_init_busy" for venue in _SUPPORTED}

    outcomes: dict[str, str] = {}
    for venue in _SUPPORTED:
        if not _configured_and_allowed(venue):
            outcomes[venue] = "not_configured_or_policy_disabled"
            continue
        _, manager_existing = _manager_entry(manager, venue)
        if manager_existing is not None:
            outcomes[venue] = "manager_present"
            continue
        if _global_candidate(broker_module, venue) is not None:
            outcomes[venue] = "global_present_wait_v280"
            continue
        try:
            broker = _construct_platform_broker(broker_module, venue)
            outcomes[venue] = _publish_missing_object(manager, broker_module, venue, broker)
        except Exception as exc:
            outcomes[venue] = f"error:{type(exc).__name__}:{exc}"
            LOGGER.error(
                "PLATFORM_OBJECT_V284_RECOVERY_FAILED marker=%s venue=%s error=%s:%s "
                "connectivity_fabricated=false trading_fail_closed=true",
                MARKER,
                venue,
                type(exc).__name__,
                exc,
            )
    return outcomes


def _delegate_v280() -> dict[str, str]:
    """Ask v280 to perform its existing bounded real reconnect/adoption pass."""
    try:
        v280 = importlib.import_module("bot.runtime_platform_activation_liveness_v280_patch")
        reconcile = getattr(v280, "reconcile_once", None)
        if not callable(reconcile):
            return {"__v280__": "reconcile_missing"}
        result = reconcile()
        return dict(result) if isinstance(result, dict) else {"__v280__": "invalid_result"}
    except Exception as exc:
        return {"__v280__": f"error:{type(exc).__name__}:{exc}"}


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_platform_object_liveness_v284"] = _READY_FLAG
        return True
    except Exception:
        return False


def _outcomes_operational(outcomes: dict[str, str]) -> bool:
    if not isinstance(outcomes, dict) or not outcomes or "__runtime__" in outcomes:
        return False
    return not any(str(value).startswith("error:") for value in outcomes.values())


def install() -> bool:
    global _LAST_LOG_SIGNATURE
    with _LOCK:
        manifest_ok = _register_manifest()
        outcomes = reconcile_once()
        delegated: dict[str, str] = {}
        if any(value in {"registered_missing_object", "global_present_wait_v280"} for value in outcomes.values()):
            delegated = _delegate_v280()
        operational = _outcomes_operational(outcomes)
        delegate_operational = not any(str(value).startswith("error:") for value in delegated.values())
        ready = bool(manifest_ok and operational and delegate_operational)
        os.environ[_READY_FLAG] = "1" if ready else "0"

        signature = repr((ready, tuple(sorted(outcomes.items())), tuple(sorted(delegated.items()))))
        if signature != _LAST_LOG_SIGNATURE:
            _LAST_LOG_SIGNATURE = signature
            log = LOGGER.critical if ready else LOGGER.error
            log(
                "PLATFORM_OBJECT_LIVENESS_V284_%s marker=%s ready=%s outcomes=%s delegated_v280=%s "
                "manifest=%s configured_object_creation_only=true credential_presence_only=true "
                "real_connect_delegated_to_v280=true connectivity_fabricated=false balance_fabricated=false "
                "position_success_fabricated=false capital_ready_granted=false execution_proof_fabricated=false "
                "user_brokers_unchanged=true writer_nonce_risk_killswitch_broker_health_ecel_min_notional_order_fill_gates_unchanged=true "
                "forced_trade=false forced_activation=false safety_gates_bypassed=false",
                "READY" if ready else "NOT_READY",
                MARKER,
                str(ready).lower(),
                outcomes,
                delegated or {"status": "not_needed"},
                str(manifest_ok).lower(),
            )
        return ready


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "reconcile_once",
    "install",
    "install_import_hook",
    "_configured_and_allowed",
    "_credential_proof",
    "_policy_allows",
    "_manager_entry",
    "_global_candidate",
    "_construct_platform_broker",
    "_publish_missing_object",
    "_delegate_v280",
    "_outcomes_operational",
]
