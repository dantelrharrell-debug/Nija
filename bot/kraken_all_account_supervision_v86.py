"""Writer-scoped Kraken connection supervision for platform and user accounts.

The existing v44 reconciler owns the platform recovery path.  This module adds
the missing per-user half: every Kraken broker already registered by the
MultiAccountBrokerManager is observed, and a disconnected broker is reconnected
through its own authenticated ``connect()`` implementation.

No connection flag, credential, nonce, balance, writer lease, or execution
authority is fabricated.  Broker I/O is scheduled only after the canonical
writer runtime has fresh exact Redis metadata, and Kraken reconnects are
serialized to preserve per-key nonce/rate-limit ordering.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from typing import Any

from bot import kraken_connection_convergence_v44_patch as v44


LOGGER = logging.getLogger("nija.kraken_all_account_supervision_v86")
MARKER = "20260810-kraken-all-account-supervision-v86"
_LOCK = threading.RLock()
_CONNECT_SERIAL_LOCK = threading.Lock()
_INFLIGHT: set[str] = set()
_FAILURES: dict[str, int] = {}
_NEXT_RETRY: dict[str, float] = {}
_WATCHDOG_STARTED = False
_WATCHDOG_STOP = threading.Event()


def _label(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip().lower()


def _writer_proof() -> tuple[bool, str]:
    runtime = v44._writer_runtime()
    if runtime is None:
        return False, "writer_runtime_missing"
    health = getattr(runtime, "_nija_lease_renewal_health", None)
    max_age_s = 15.0
    if callable(health):
        try:
            _ok, _reason, _age_s, observed_max_age_s = health()
            max_age_s = max(5.0, float(observed_max_age_s or max_age_s))
        except Exception:
            pass
    proof = v44._exact_writer_renewal_proof(runtime, max_age_s)
    if not proof.get("ok"):
        return False, str(proof.get("reason") or "exact_writer_proof_failed")
    return True, "exact_writer_renewal_proof"


def _user_records(manager: Any) -> list[tuple[str, str, Any, Any]]:
    """Return unique registered Kraken users, including disconnected brokers."""
    records: dict[str, tuple[str, str, Any, Any]] = {}
    all_users = getattr(manager, "_all_user_brokers", {})
    try:
        all_items = list(all_users.items())
    except Exception:
        all_items = []
    for key, broker in all_items:
        if not isinstance(key, tuple) or len(key) != 2:
            continue
        user_id, broker_type = key
        if _label(broker_type) != "kraken" or broker is None:
            continue
        account_id = f"user:{user_id}:kraken"
        records[account_id] = (account_id, str(user_id), broker_type, broker)

    connected_users = getattr(manager, "user_brokers", {})
    try:
        connected_items = list(connected_users.items())
    except Exception:
        connected_items = []
    for user_id, mapping in connected_items:
        try:
            broker_items = list(mapping.items())
        except Exception:
            continue
        for broker_type, broker in broker_items:
            if _label(broker_type) != "kraken" or broker is None:
                continue
            account_id = f"user:{user_id}:kraken"
            records[account_id] = (account_id, str(user_id), broker_type, broker)

    # Registry truth includes users whose broker could not be constructed,
    # whose authenticated connection failed, or whose credentials are absent.
    # Preserve those records with broker=None so reporting cannot silently
    # shrink the denominator.  _schedule() never performs broker I/O for them.
    metadata = getattr(manager, "_user_metadata", {})
    try:
        metadata_items = list(metadata.items())
    except Exception:
        metadata_items = []
    for user_id, user_metadata in metadata_items:
        broker_map = user_metadata.get("brokers", {}) if isinstance(user_metadata, dict) else {}
        try:
            broker_types = list(broker_map)
        except Exception:
            broker_types = []
        for broker_type in broker_types:
            if _label(broker_type) != "kraken":
                continue
            account_id = f"user:{user_id}:kraken"
            records.setdefault(account_id, (account_id, str(user_id), broker_type, None))

    for registry_name in ("_failed_user_connections", "_users_without_credentials"):
        registry = getattr(manager, registry_name, {})
        try:
            registry_keys = list(registry)
        except Exception:
            registry_keys = []
        for key in registry_keys:
            if not isinstance(key, tuple) or len(key) != 2:
                continue
            user_id, broker_type = key
            if _label(broker_type) != "kraken":
                continue
            account_id = f"user:{user_id}:kraken"
            records.setdefault(account_id, (account_id, str(user_id), broker_type, None))
    return [records[key] for key in sorted(records)]


def _retry_delay(failures: int) -> float:
    try:
        base = max(5.0, float(os.environ.get("NIJA_KRAKEN_USER_RECONNECT_BASE_S", "10") or 10))
    except (TypeError, ValueError):
        base = 10.0
    try:
        ceiling = max(base, float(os.environ.get("NIJA_KRAKEN_USER_RECONNECT_MAX_S", "300") or 300))
    except (TypeError, ValueError):
        ceiling = 300.0
    return min(ceiling, base * (2 ** max(0, min(failures - 1, 8))))


def _mark_connected(manager: Any, user_id: str, broker_type: Any, broker: Any) -> None:
    if not bool(getattr(broker, "connected", False)):
        return
    user_map = getattr(manager, "user_brokers", None)
    if isinstance(user_map, dict):
        user_map.setdefault(user_id, {})[broker_type] = broker
    failed = getattr(manager, "_failed_user_connections", None)
    if isinstance(failed, dict):
        failed.pop((user_id, broker_type), None)


def _connect_account(
    manager: Any,
    account_id: str,
    user_id: str,
    broker_type: Any,
    broker: Any,
) -> None:
    try:
        with _CONNECT_SERIAL_LOCK:
            if bool(getattr(broker, "connected", False)):
                _mark_connected(manager, user_id, broker_type, broker)
                with _LOCK:
                    _FAILURES.pop(account_id, None)
                    _NEXT_RETRY.pop(account_id, None)
                return

            proof_ok, proof_reason = _writer_proof()
            if not proof_ok:
                with _LOCK:
                    _NEXT_RETRY[account_id] = time.monotonic() + 5.0
                LOGGER.warning(
                    "KRAKEN_USER_RECONNECT_BLOCKED marker=%s account=%s reason=%s "
                    "broker_io=false fail_closed=true",
                    MARKER,
                    account_id,
                    proof_reason,
                )
                return

            user_config = getattr(manager, "user_configs", {}).get(user_id)
            resync = getattr(manager, "_resync_single_user_kraken_nonce", None)
            if user_config is not None and callable(resync):
                try:
                    resync(user_config)
                except Exception as exc:
                    LOGGER.warning(
                        "KRAKEN_USER_NONCE_RESYNC_FAILED marker=%s account=%s error=%s:%s",
                        MARKER,
                        account_id,
                        type(exc).__name__,
                        exc,
                    )

            connect = getattr(broker, "connect", None)
            if not callable(connect):
                raise RuntimeError("broker_connect_unavailable")
            connect()
            if not bool(getattr(broker, "connected", False)):
                raise RuntimeError("authenticated_connect_did_not_confirm_connected")

            _mark_connected(manager, user_id, broker_type, broker)
            with _LOCK:
                _FAILURES.pop(account_id, None)
                _NEXT_RETRY.pop(account_id, None)
            LOGGER.critical(
                "KRAKEN_USER_RECONNECTED marker=%s account=%s "
                "authenticated=true fabricated_connected=false",
                MARKER,
                account_id,
            )
    except Exception as exc:
        with _LOCK:
            failures = _FAILURES.get(account_id, 0) + 1
            _FAILURES[account_id] = failures
            delay = _retry_delay(failures)
            _NEXT_RETRY[account_id] = time.monotonic() + delay
        LOGGER.warning(
            "KRAKEN_USER_RECONNECT_FAILED marker=%s account=%s failures=%d "
            "retry_s=%.1f error=%s:%s isolated=true",
            MARKER,
            account_id,
            failures,
            delay,
            type(exc).__name__,
            exc,
        )
    finally:
        with _LOCK:
            _INFLIGHT.discard(account_id)


def _schedule(manager: Any, record: tuple[str, str, Any, Any]) -> str:
    account_id, user_id, broker_type, broker = record
    if broker is None:
        missing = getattr(manager, "_users_without_credentials", {})
        if (user_id, broker_type) in missing:
            return "credentials_not_configured"
        return "broker_unavailable"
    if bool(getattr(broker, "connected", False)):
        _mark_connected(manager, user_id, broker_type, broker)
        with _LOCK:
            _FAILURES.pop(account_id, None)
            _NEXT_RETRY.pop(account_id, None)
        return "connected"
    if getattr(broker, "credentials_configured", None) is False:
        return "credentials_not_configured"

    now = time.monotonic()
    with _LOCK:
        if account_id in _INFLIGHT:
            return "reconnect_inflight"
        if now < _NEXT_RETRY.get(account_id, 0.0):
            return "backoff"
        _INFLIGHT.add(account_id)
    threading.Thread(
        target=_connect_account,
        args=(manager, account_id, user_id, broker_type, broker),
        name=f"KrakenUserReconnect-{user_id}",
        daemon=True,
    ).start()
    return "reconnect_scheduled"


def reconcile_once(manager: Any = None) -> dict[str, Any]:
    if manager is None:
        try:
            # ``get_broker_manager`` is the canonical singleton accessor in
            # multi_account_broker_manager.  Observe only an already-loaded
            # module: importing the broker graph from this watchdog would race
            # the canonical main-thread startup handoff.
            module = sys.modules.get("bot.multi_account_broker_manager")
            get_broker_manager = getattr(module, "get_broker_manager", None)
            if not callable(get_broker_manager):
                raise RuntimeError("canonical_manager_not_loaded")
            manager = get_broker_manager()
        except Exception as exc:
            return {"ok": False, "reason": f"manager_unavailable:{type(exc).__name__}:{exc}"}
    records = _user_records(manager)
    states = {account_id: _schedule(manager, record) for record in records for account_id in [record[0]]}
    disconnected = sum(1 for state in states.values() if state != "connected")
    registered = len(records)
    return {
        "ok": registered == 0 or disconnected == 0,
        "reason": (
            "no_registered_kraken_users"
            if registered == 0
            else "all_registered_kraken_users_connected"
            if disconnected == 0
            else "recovery_active"
        ),
        "registered": registered,
        "connected": registered - disconnected,
        "disconnected": disconnected,
        "states": states,
    }


def _watchdog() -> None:
    """Continuously supervise registered Kraken users after canonical handoff."""
    try:
        interval = max(
            2.0,
            float(os.environ.get("NIJA_KRAKEN_USER_SUPERVISION_POLL_S", "5") or 5),
        )
    except (TypeError, ValueError):
        interval = 5.0
    last_signature = ""
    while not _WATCHDOG_STOP.wait(interval):
        try:
            state = reconcile_once()
            signature = (
                f"{state.get('registered')}:{state.get('connected')}:"
                f"{state.get('disconnected')}:{state.get('reason')}"
            )
            if signature == last_signature:
                continue
            log = LOGGER.info if state.get("ok") else LOGGER.warning
            log(
                "KRAKEN_USER_SUPERVISION marker=%s registered=%s connected=%s "
                "disconnected=%s reason=%s authenticated_reconnect_only=true",
                MARKER,
                state.get("registered", 0),
                state.get("connected", 0),
                state.get("disconnected", 0),
                state.get("reason", "unknown"),
            )
            last_signature = signature
        except Exception as exc:
            LOGGER.warning(
                "KRAKEN_USER_SUPERVISION_ERROR marker=%s error=%s:%s isolated=true",
                MARKER,
                type(exc).__name__,
                exc,
            )


def install() -> bool:
    global _WATCHDOG_STARTED
    with _LOCK:
        if not _WATCHDOG_STARTED:
            _WATCHDOG_STARTED = True
            threading.Thread(
                target=_watchdog,
                name="KrakenAllAccountSupervisionV86",
                daemon=True,
            ).start()
    os.environ["NIJA_KRAKEN_ALL_ACCOUNT_SUPERVISION_V86_INSTALLED"] = "1"
    LOGGER.critical(
        "KRAKEN_ALL_ACCOUNT_SUPERVISION_V86_INSTALLED marker=%s "
        "platform=v44 users=authenticated_per_account writer_scoped=true "
        "continuous_supervision=true",
        MARKER,
    )
    return True


__all__ = ["MARKER", "install", "reconcile_once", "_user_records", "_writer_proof"]
