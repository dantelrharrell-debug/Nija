"""Converge registered Kraken user accounts onto real authenticated brokers.

This patch extends v86 without weakening its writer/nonce/capital safeguards.
The missing case in v86 is a registered user whose broker object is absent, or
whose broker was constructed before credentials became available.  In those
states v86 returns ``broker_unavailable`` / ``credentials_not_configured`` and
never asks the canonical manager to reconstruct the broker.

v90 performs a bounded reconstruction through
``MultiAccountBrokerManager.add_user_broker``.  That canonical API constructs
the isolated per-user broker and performs its real authenticated ``connect()``.
No connected flag, credential, balance, trading eligibility, execution
authority, or kill-switch state is synthesized here.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

from bot import kraken_all_account_supervision_v86 as v86


LOGGER = logging.getLogger("nija.kraken_user_connection_convergence_v90")
MARKER = "20260814-kraken-user-connection-convergence-v90"
_LOCK = threading.RLock()
_PATCHED = False
_MONITOR_STARTED = False
_ORIGINAL_SCHEDULE = None
_NEXT_REBUILD: dict[str, float] = {}
_REBUILD_FAILURES: dict[str, int] = {}
_LAST_MONITOR_SIGNATURE = ""


def _rebuild_delay(failures: int) -> float:
    try:
        base = max(15.0, float(os.environ.get("NIJA_KRAKEN_USER_REBUILD_BASE_S", "30") or 30))
    except (TypeError, ValueError):
        base = 30.0
    try:
        ceiling = max(base, float(os.environ.get("NIJA_KRAKEN_USER_REBUILD_MAX_S", "300") or 300))
    except (TypeError, ValueError):
        ceiling = 300.0
    return min(ceiling, base * (2 ** max(0, min(failures - 1, 4))))


def _set_rebuild_backoff(account_id: str, *, failed: bool) -> None:
    with _LOCK:
        if failed:
            failures = _REBUILD_FAILURES.get(account_id, 0) + 1
            _REBUILD_FAILURES[account_id] = failures
        else:
            failures = 1
            _REBUILD_FAILURES.pop(account_id, None)
        _NEXT_REBUILD[account_id] = time.monotonic() + _rebuild_delay(failures)


def _rebuild_due(account_id: str) -> bool:
    with _LOCK:
        return time.monotonic() >= _NEXT_REBUILD.get(account_id, 0.0)


def _recover_broker(
    manager: Any,
    account_id: str,
    user_id: str,
    broker_type: Any,
) -> tuple[Any, str]:
    """Reconstruct one user broker through the canonical manager, fail closed."""
    if not _rebuild_due(account_id):
        return None, "rebuild_backoff"

    proof_ok, proof_reason = v86._writer_proof()
    if not proof_ok:
        _set_rebuild_backoff(account_id, failed=False)
        LOGGER.warning(
            "KRAKEN_USER_BROKER_REBUILD_BLOCKED marker=%s account=%s reason=%s "
            "broker_io=false fail_closed=true",
            MARKER,
            account_id,
            proof_reason,
        )
        return None, f"writer_proof_blocked:{proof_reason}"

    config = v86._recover_user_config(manager, user_id)
    if config is None:
        _set_rebuild_backoff(account_id, failed=True)
        LOGGER.warning(
            "KRAKEN_USER_BROKER_REBUILD_BLOCKED marker=%s account=%s "
            "reason=user_config_unavailable broker_io=false fail_closed=true",
            MARKER,
            account_id,
        )
        return None, "user_config_unavailable"

    add_user_broker = getattr(manager, "add_user_broker", None)
    if not callable(add_user_broker):
        _set_rebuild_backoff(account_id, failed=True)
        return None, "canonical_add_user_broker_unavailable"

    try:
        broker = add_user_broker(user_id, broker_type)
    except Exception as exc:
        _set_rebuild_backoff(account_id, failed=True)
        LOGGER.warning(
            "KRAKEN_USER_BROKER_REBUILD_FAILED marker=%s account=%s error=%s:%s isolated=true",
            MARKER,
            account_id,
            type(exc).__name__,
            exc,
        )
        return None, f"broker_rebuild_failed:{type(exc).__name__}"

    if broker is None:
        _set_rebuild_backoff(account_id, failed=True)
        LOGGER.warning(
            "KRAKEN_USER_BROKER_REBUILD_FAILED marker=%s account=%s "
            "reason=canonical_manager_returned_none isolated=true",
            MARKER,
            account_id,
        )
        return None, "broker_rebuild_returned_none"

    key = (user_id, broker_type)
    all_users = getattr(manager, "_all_user_brokers", None)
    if isinstance(all_users, dict):
        all_users[key] = broker

    if bool(getattr(broker, "connected", False)):
        v86._mark_connected(manager, user_id, broker_type, broker)
        with _LOCK:
            _REBUILD_FAILURES.pop(account_id, None)
            _NEXT_REBUILD.pop(account_id, None)
        LOGGER.critical(
            "KRAKEN_USER_BROKER_REBUILT_CONNECTED marker=%s account=%s "
            "authenticated=true fabricated_connected=false",
            MARKER,
            account_id,
        )
        return broker, "connected"

    if getattr(broker, "credentials_configured", None) is False:
        missing = getattr(manager, "_users_without_credentials", None)
        if isinstance(missing, dict):
            missing[key] = True
        _set_rebuild_backoff(account_id, failed=False)
        LOGGER.warning(
            "KRAKEN_USER_BROKER_REBUILT_DISCONNECTED marker=%s account=%s "
            "reason=credentials_not_configured fabricated_credentials=false",
            MARKER,
            account_id,
        )
        return broker, "credentials_not_configured"

    failed = getattr(manager, "_failed_user_connections", None)
    if isinstance(failed, dict):
        failed[key] = "reconstructed_broker_authenticated_connect_not_confirmed"
    _set_rebuild_backoff(account_id, failed=False)
    LOGGER.warning(
        "KRAKEN_USER_BROKER_REBUILT_DISCONNECTED marker=%s account=%s "
        "reason=authenticated_connect_not_confirmed next=v86_reconnect fabricated_connected=false",
        MARKER,
        account_id,
    )
    return broker, "broker_recovered_reconnect_pending"


def _schedule_v90(manager: Any, record: tuple[str, str, Any, Any]) -> str:
    account_id, user_id, broker_type, broker = record
    original = _ORIGINAL_SCHEDULE or v86._schedule

    missing_object = broker is None
    stale_credentials = broker is not None and getattr(broker, "credentials_configured", None) is False
    if not missing_object and not stale_credentials:
        return original(manager, record)

    recovered, state = _recover_broker(manager, account_id, user_id, broker_type)
    if state == "connected":
        return "connected"
    if recovered is not None and bool(getattr(recovered, "connected", False)):
        return "connected"

    # Do not immediately call connect a second time after canonical reconstruction.
    # The next v86 pass owns serialized reconnect/retry for a real broker object.
    if recovered is not None:
        return state

    if state == "rebuild_backoff":
        return "credentials_not_configured" if stale_credentials else "broker_unavailable"
    return state


def _monitor() -> None:
    global _LAST_MONITOR_SIGNATURE
    try:
        interval = max(2.0, float(os.environ.get("NIJA_KRAKEN_USER_V90_POLL_S", "5") or 5))
    except (TypeError, ValueError):
        interval = 5.0
    while True:
        time.sleep(interval)
        try:
            state = v86.reconcile_once()
            states = state.get("states", {}) if isinstance(state, dict) else {}
            signature = repr((
                state.get("registered", 0) if isinstance(state, dict) else 0,
                state.get("connected", 0) if isinstance(state, dict) else 0,
                state.get("disconnected", 0) if isinstance(state, dict) else 0,
                sorted(states.items()) if isinstance(states, dict) else [],
            ))
            if signature == _LAST_MONITOR_SIGNATURE:
                continue
            _LAST_MONITOR_SIGNATURE = signature
            ready = bool(state.get("ok")) if isinstance(state, dict) else False
            os.environ["NIJA_KRAKEN_USER_CONNECTIONS_READY"] = "1" if ready else "0"
            log = LOGGER.critical if ready else LOGGER.warning
            log(
                "KRAKEN_USER_CONNECTION_CONVERGENCE_V90 marker=%s registered=%s connected=%s "
                "disconnected=%s states=%s authenticated_only=true fabricated_readiness=false",
                MARKER,
                state.get("registered", 0) if isinstance(state, dict) else 0,
                state.get("connected", 0) if isinstance(state, dict) else 0,
                state.get("disconnected", 0) if isinstance(state, dict) else 0,
                states,
            )
        except Exception as exc:
            os.environ["NIJA_KRAKEN_USER_CONNECTIONS_READY"] = "0"
            LOGGER.warning(
                "KRAKEN_USER_CONNECTION_CONVERGENCE_V90_ERROR marker=%s error=%s:%s isolated=true",
                MARKER,
                type(exc).__name__,
                exc,
            )


def install_import_hook() -> bool:
    global _PATCHED, _MONITOR_STARTED, _ORIGINAL_SCHEDULE
    with _LOCK:
        if not _PATCHED:
            current = getattr(v86, "_schedule", None)
            if not callable(current):
                raise RuntimeError("v86_schedule_unavailable")
            if getattr(current, "_nija_v90_user_connection_convergence", False):
                _PATCHED = True
            else:
                _ORIGINAL_SCHEDULE = current
                setattr(_schedule_v90, "_nija_v90_user_connection_convergence", True)
                v86._schedule = _schedule_v90
                _PATCHED = True
        if not _MONITOR_STARTED:
            _MONITOR_STARTED = True
            threading.Thread(
                target=_monitor,
                name="KrakenUserConnectionConvergenceV90",
                daemon=True,
            ).start()
    os.environ["NIJA_KRAKEN_USER_CONNECTION_CONVERGENCE_V90_INSTALLED"] = "1"
    LOGGER.critical(
        "KRAKEN_USER_CONNECTION_CONVERGENCE_V90_INSTALLED marker=%s "
        "canonical_rebuild=true authenticated_only=true exact_writer_proof=true "
        "capital_eligibility_unchanged=true kill_switch_unchanged=true",
        MARKER,
    )
    return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_recover_broker",
    "_schedule_v90",
]
