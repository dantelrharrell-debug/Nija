"""Keep process-local Kraken read-lock contention out of broker failure health (v237).

A KrakenReadLockBusy read still fails closed, but it is not evidence that Kraken,
credentials, nonce, or the account are unhealthy. Patch every loaded KrakenBroker
identity that owns the balance path and restore only the exact pre-call health fields
when v234 proves contention occurred during that call. The canonical balance/private
read owner is ``bot.broker_manager.KrakenBroker``; broker_integration exposes an adapter
layer and is not a valid readiness prerequisite for this guard. Genuine
exchange/API/auth/nonce/order/HTTP failures remain authoritative.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.runtime_kraken_local_contention_health_v237")
MARKER = "20260826-kraken-local-contention-health-v237"
_FLAG = "NIJA_KRAKEN_LOCAL_CONTENTION_HEALTH_V237_READY"
_PATCH_ATTR = "_nija_kraken_local_contention_health_v237"
_BALANCE_PATCH_ATTR = "_nija_kraken_balance_local_contention_v237"
_MODULES = ("bot.broker_integration", "broker_integration", "bot.broker_manager", "broker_manager")


def _is_local_contention(broker_name: str, reason: str) -> bool:
    name = str(broker_name or "").strip().lower()
    text = str(reason or "").strip().lower()
    return "kraken" in name and any(token in text for token in (
        "kraken read lock busy", "krakenreadlockbusy", "kraken_read_lock_v212_busy", "local_read_lock_timeout"
    ))


def _clear_local_only_state(self: Any, broker_name: str) -> tuple[bool, int]:
    lock = getattr(self, "_lock", None)
    states = getattr(self, "_states", None)
    if lock is None or not isinstance(states, dict):
        return False, 0
    with lock:
        state = states.get(broker_name)
        if state is None:
            return False, 0
        previous = int(getattr(state, "consecutive_errors", 0) or 0)
        last_reason = str(getattr(state, "last_error_reason", "") or "")
        if previous <= 0 and not bool(getattr(state, "is_dead", False)):
            return False, 0
        if last_reason and not _is_local_contention(broker_name, last_reason):
            return False, previous
        state.consecutive_errors = 0
        state.last_error_reason = ""
        if bool(getattr(state, "is_dead", False)):
            state.is_dead = False
            state.dead_since = None
            state.retry_attempts = 0
        return True, previous


def _patch_failure_manager() -> bool:
    module = importlib.import_module("bot.broker_failure_manager")
    cls = getattr(module, "BrokerFailureManager", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "record_error", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def record_error_v237(self: Any, broker_name: str, reason: str = "") -> bool:
        if _is_local_contention(broker_name, reason):
            cleared, previous = _clear_local_only_state(self, broker_name)
            LOGGER.warning(
                "KRAKEN_LOCAL_CONTENTION_V237_EXCLUDED marker=%s broker=%s reason=%s current_read_fail_closed=true "
                "broker_failure_streak_incremented=false local_only_streak_cleared=%s previous_consecutive_errors=%s "
                "exchange_unavailability_unproven=true auth_nonce_order_http_errors_unchanged=true safety_gates_bypassed=false",
                MARKER, broker_name, str(reason)[:160], str(cleared).lower(), previous,
            )
            return False
        return bool(current(self, broker_name, reason))

    setattr(record_error_v237, _PATCH_ATTR, True)
    setattr(record_error_v237, "__wrapped__", current)
    cls.record_error = record_error_v237
    return True


def _busy_epoch() -> float:
    try:
        return float(os.environ.get("NIJA_KRAKEN_READ_LOCK_V234_BUSY_EPOCH", "0") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _health_snapshot(obj: Any) -> dict[str, Any]:
    fields = ("_balance_fetch_errors", "_is_available", "exit_only_mode", "kraken_health", "_consecutive_errors", "consecutive_errors", "connected", "is_connected", "_connected", "trading_eligible")
    return {name: getattr(obj, name) for name in fields if hasattr(obj, name)}


def _restore_exact(obj: Any, before: dict[str, Any]) -> tuple[str, ...]:
    restored: list[str] = []
    for name, value in before.items():
        try:
            if getattr(obj, name, None) != value:
                setattr(obj, name, value)
                restored.append(name)
        except Exception:
            pass
    return tuple(sorted(restored))


def _patch_balance_class(cls: type) -> bool:
    current = getattr(cls, "get_account_balance", None)
    if not callable(current):
        return False
    if bool(getattr(current, _BALANCE_PATCH_ATTR, False)):
        return True

    @wraps(current)
    def get_account_balance_v237(self: Any, *args: Any, **kwargs: Any):
        before_epoch = _busy_epoch()
        before_health = _health_snapshot(self)
        try:
            result = current(self, *args, **kwargs)
        except BaseException:
            if _busy_epoch() > before_epoch:
                restored = _restore_exact(self, before_health)
                LOGGER.critical("KRAKEN_LOCAL_CONTENTION_V237_DIRECT_HEALTH_RESTORED marker=%s account=%s restored_fields=%s current_read_fail_closed=true exception_unchanged=true exact_precall_health_only=true genuine_exchange_errors_unchanged=true safety_gates_bypassed=false", MARKER, str(getattr(self, "account_identifier", getattr(self, "account_id", "unknown"))), ",".join(restored) or "none")
            raise
        if _busy_epoch() > before_epoch:
            restored = _restore_exact(self, before_health)
            LOGGER.critical("KRAKEN_LOCAL_CONTENTION_V237_DIRECT_HEALTH_RESTORED marker=%s account=%s restored_fields=%s current_read_fail_closed=true balance_result_unchanged=true exact_precall_health_only=true genuine_exchange_errors_unchanged=true safety_gates_bypassed=false", MARKER, str(getattr(self, "account_identifier", getattr(self, "account_id", "unknown"))), ",".join(restored) or "none")
        return result

    setattr(get_account_balance_v237, _BALANCE_PATCH_ATTR, True)
    setattr(get_account_balance_v237, "__wrapped__", current)
    cls.get_account_balance = get_account_balance_v237
    return True


def _patch_kraken_balance_health() -> bool:
    classes: dict[int, type] = {}
    canonical_manager_found = False
    for name in _MODULES:
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            try:
                module = importlib.import_module(name)
            except Exception:
                continue
        cls = getattr(module, "KrakenBroker", None)
        if isinstance(cls, type) and callable(getattr(cls, "get_account_balance", None)):
            classes[id(cls)] = cls
            # The live ``KrakenBroker`` class belongs to
            # ``bot.broker_manager``.  ``bot.broker_integration`` has a
            # differently shaped ``KrakenBrokerAdapter`` and must not be used
            # as proof that the manager class exists.
            if str(getattr(module, "__name__", name)) == "bot.broker_manager":
                canonical_manager_found = True
    return bool(
        classes
        and canonical_manager_found
        and all(_patch_balance_class(cls) for cls in classes.values())
    )


def install() -> bool:
    try:
        v234 = importlib.import_module("bot.runtime_kraken_read_lock_recovery_v234_patch")
        installer = getattr(v234, "install", None)
        v234_ready = bool(callable(installer) and installer())
        manager_patched = _patch_failure_manager()
        balance_patched = _patch_kraken_balance_health()
        ready = bool(v234_ready and manager_patched and balance_patched)
    except Exception as exc:
        LOGGER.error("KRAKEN_LOCAL_CONTENTION_V237_INSTALL_ERROR marker=%s error=%s:%s trading_fail_closed=true", MARKER, type(exc).__name__, exc)
        ready = False
    os.environ[_FLAG] = "1" if ready else "0"
    if ready:
        LOGGER.critical("KRAKEN_LOCAL_CONTENTION_V237_READY marker=%s ready=true canonical_broker_manager=true local_read_lock_only=true broker_failure_streak_excluded=true direct_balance_health_protected=true current_read_fail_closed=true genuine_exchange_errors_unchanged=true execution_authority_unchanged=true nonce_policy_unchanged=true forced_trade=false safety_gates_bypassed=false", MARKER)
    return ready


def install_import_hook() -> bool:
    return install()


__all__ = ["MARKER", "install", "install_import_hook", "_is_local_contention", "_clear_local_only_state", "_patch_kraken_balance_health"]
