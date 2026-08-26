"""Keep process-local Kraken read-lock contention out of broker failure health (v237).

KrakenReadLockBusy is a process-local synchronization failure, not evidence that the
Kraken exchange, credentials, nonce, or account are unhealthy. The current read stays
fail-closed and v234 remains responsible for bounded recovery, but this condition must
not create or preserve a broker failure streak/DEAD/EXIT-ONLY state.

Production on 2026-08-26 exposed a second health path: KrakenBroker.get_account_balance
increments ``_balance_fetch_errors`` and flips ``_is_available``/``exit_only_mode``
directly after swallowing the local-lock exception. That bypasses BrokerFailureManager
entirely. v237 now snapshots those direct health fields before each Kraken balance call.
If and only if v234 proves a process-local read-lock starvation episode occurred during
the call, v237 restores the exact pre-call health fields. It never improves health
beyond the pre-call state, never fabricates a balance, and never clears a prior genuine
exchange/auth/nonce/order/HTTP failure.
"""
from __future__ import annotations

import importlib
import logging
import os
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_kraken_local_contention_health_v237")
MARKER = "20260826-kraken-local-contention-health-v237"
_FLAG = "NIJA_KRAKEN_LOCAL_CONTENTION_HEALTH_V237_READY"
_PATCH_ATTR = "_nija_kraken_local_contention_health_v237"
_BALANCE_PATCH_ATTR = "_nija_kraken_balance_local_contention_v237"


def _is_local_contention(broker_name: str, reason: str) -> bool:
    name = str(broker_name or "").strip().lower()
    text = str(reason or "").strip().lower()
    if "kraken" not in name:
        return False
    return (
        "kraken read lock busy" in text
        or "krakenreadlockbusy" in text
        or "kraken_read_lock_v212_busy" in text
        or "local_read_lock_timeout" in text
    )


def _clear_local_only_state(self: Any, broker_name: str) -> tuple[bool, int]:
    """Clear only manager health state whose recorded cause is local contention."""
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
                "KRAKEN_LOCAL_CONTENTION_V237_EXCLUDED marker=%s broker=%s reason=%s "
                "current_read_fail_closed=true broker_failure_streak_incremented=false "
                "local_only_streak_cleared=%s previous_consecutive_errors=%s "
                "exchange_unavailability_unproven=true v234_recovery_authoritative=true "
                "auth_nonce_order_http_errors_unchanged=true safety_gates_bypassed=false",
                MARKER, broker_name, str(reason)[:160], str(cleared).lower(), previous,
            )
            return False
        return bool(current(self, broker_name, reason))

    setattr(record_error_v237, _PATCH_ATTR, True)
    setattr(record_error_v237, "__wrapped__", current)
    cls.record_error = record_error_v237
    return True


def _v234_starving() -> bool:
    return str(os.environ.get("NIJA_KRAKEN_READ_LOCK_V234_STARVING", "") or "").strip() == "1"


def _patch_kraken_balance_health() -> bool:
    """Stop swallowed local-lock failures from mutating direct broker health.

    The wrapper can only restore the exact pre-call state; therefore a broker that
    was already unavailable/exit-only due to a genuine prior failure stays that way.
    """
    module = importlib.import_module("bot.broker_manager")
    cls = getattr(module, "KrakenBroker", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "get_account_balance", None)
    if not callable(current):
        return False
    if bool(getattr(current, _BALANCE_PATCH_ATTR, False)):
        return True

    @wraps(current)
    def get_account_balance_v237(self: Any, *args: Any, **kwargs: Any):
        before_errors = int(getattr(self, "_balance_fetch_errors", 0) or 0)
        before_available = bool(getattr(self, "_is_available", True))
        before_exit_only = bool(getattr(self, "exit_only_mode", False))
        before_health = getattr(self, "kraken_health", None)
        starving_before = _v234_starving()

        result = current(self, *args, **kwargs)

        after_errors = int(getattr(self, "_balance_fetch_errors", 0) or 0)
        # v234 sets STARVING synchronously on the exact KrakenReadLockBusy path.
        # Require a new/increased direct error in this call so an old starvation
        # episode cannot mask an unrelated later exchange failure.
        local_busy_this_call = bool(_v234_starving() and after_errors > before_errors)
        if local_busy_this_call:
            self._balance_fetch_errors = before_errors
            self._is_available = before_available
            self.exit_only_mode = before_exit_only
            if before_health is not None:
                self.kraken_health = before_health
            LOGGER.critical(
                "KRAKEN_LOCAL_CONTENTION_V237_DIRECT_HEALTH_RESTORED marker=%s account=%s "
                "errors_before=%d errors_after=%d restored_errors=%d available_restored=%s "
                "exit_only_restored=%s starvation_preexisting=%s current_read_fail_closed=true "
                "balance_result_unchanged=true prior_health_not_improved=true genuine_exchange_errors_unchanged=true "
                "execution_authority_unchanged=true nonce_policy_unchanged=true safety_gates_bypassed=false",
                MARKER,
                str(getattr(self, "account_identifier", "unknown")),
                before_errors,
                after_errors,
                before_errors,
                str(before_available).lower(),
                str(before_exit_only).lower(),
                str(starving_before).lower(),
            )
        return result

    setattr(get_account_balance_v237, _BALANCE_PATCH_ATTR, True)
    setattr(get_account_balance_v237, "__wrapped__", current)
    cls.get_account_balance = get_account_balance_v237
    return True


def install() -> bool:
    try:
        v234 = importlib.import_module("bot.runtime_kraken_read_lock_recovery_v234_patch")
        installer = getattr(v234, "install", None)
        v234_ready = bool(callable(installer) and installer())
        manager_patched = _patch_failure_manager()
        balance_patched = _patch_kraken_balance_health()
        ready = bool(v234_ready and manager_patched and balance_patched)
    except Exception as exc:
        LOGGER.error(
            "KRAKEN_LOCAL_CONTENTION_V237_INSTALL_ERROR marker=%s error=%s:%s trading_fail_closed=true",
            MARKER, type(exc).__name__, exc,
        )
        ready = False
    os.environ[_FLAG] = "1" if ready else "0"
    if ready:
        LOGGER.critical(
            "KRAKEN_LOCAL_CONTENTION_V237_READY marker=%s ready=true local_read_lock_only=true "
            "broker_failure_streak_excluded=true direct_balance_health_protected=true "
            "local_only_stale_health_repair=true v234_required=true current_read_fail_closed=true "
            "genuine_exchange_errors_unchanged=true execution_authority_unchanged=true "
            "nonce_policy_unchanged=true forced_trade=false safety_gates_bypassed=false",
            MARKER,
        )
    return ready


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_is_local_contention",
    "_clear_local_only_state",
    "_patch_kraken_balance_health",
]
