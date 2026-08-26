"""Recover from a permanently wedged process-local Kraken private-read lock.

Production on 2026-08-26 proved that v212's bounded 3 s lock admission correctly
fails closed, but a process-local lock can remain unavailable across many
successive reads. Because ``threading`` locks cannot be safely force-released by
a non-owner thread, the safe automatic recovery for a stale in-process owner is
to recycle the worker process after repeated failed admissions over a bounded
observation window.

This patch does NOT bypass the Kraken lock, fabricate balances, clear the kill
switch, grant execution authority, change nonce policy, or retry mutating calls.
It observes ``KrakenReadLockBusy`` failures from the existing v121 wrapper. A
successful Kraken private call clears the starvation episode. Quiet time alone
does not: production probes can be farther apart than the old quiet-reset window,
which previously prevented the stale threshold from ever accumulating.

The recycle threshold is intentionally shorter than the account-level broker
failure escalation window. Local lock contention is a process-local liveness
failure, not proof that Kraken or a user's credentials are unavailable. Recycling
early prevents a wedged reader from accumulating dozens of misleading balance
failures and pushing otherwise healthy accounts into EXIT-ONLY solely because a
local read lock remained owned by a dead/stalled worker.

Mutating calls remain serialized by the original broker implementation. A
mutating call suppresses recovery while active, preventing a recycle from being
initiated by this patch during a known order/cancel/edit request.
"""
from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.runtime_kraken_read_lock_recovery_v234")
MARKER = "20260826-runtime-kraken-read-lock-recovery-v234"
_PATCH_ATTR = "_nija_runtime_kraken_read_lock_recovery_v234"
_LOCK = threading.RLock()
_STARTED = False
_BUSY_SINCE = 0.0
_LAST_BUSY = 0.0
_BUSY_COUNT = 0
_ACTIVE_MUTATIONS = 0
_RECYCLE_REQUESTED = False

_MUTATING = {
    "AddOrder", "AddOrderBatch", "CancelOrder", "CancelOrderBatch",
    "CancelAll", "CancelAllOrdersAfter", "EditOrder",
}


def _float_env(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _stale_after_s() -> float:
    # Recovery must beat broker-level consecutive-error escalation. We still
    # require >=3 independent lock-busy observations and no mutating request.
    return _float_env("NIJA_KRAKEN_READ_LOCK_RECYCLE_AFTER_S", 15.0, 10.0, 120.0)


def _quiet_reset_s() -> float:
    # Retained for configuration/log compatibility. Quiet time is diagnostic;
    # only an actual successful private call proves the lock recovered.
    return _float_env("NIJA_KRAKEN_READ_LOCK_QUIET_RESET_S", 8.0, 3.0, 30.0)


def _method_from_call(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    if args:
        return str(args[0] or "")
    return str(kwargs.get("method") or "")


def _is_lock_busy(exc: BaseException) -> bool:
    try:
        from bot.kraken_read_timeout_v121_patch import KrakenReadLockBusy
        if isinstance(exc, KrakenReadLockBusy):
            return True
    except Exception:
        pass
    return "kraken read lock busy" in str(exc or "").lower()


def _note_busy() -> None:
    global _BUSY_SINCE, _LAST_BUSY, _BUSY_COUNT
    now = time.monotonic()
    with _LOCK:
        if _BUSY_SINCE <= 0.0:
            _BUSY_SINCE = now
            _BUSY_COUNT = 0
        _LAST_BUSY = now
        _BUSY_COUNT += 1
        count = _BUSY_COUNT
        age = max(0.0, now - _BUSY_SINCE)
    os.environ["NIJA_KRAKEN_READ_LOCK_V234_STARVING"] = "1"
    os.environ["NIJA_KRAKEN_READ_LOCK_V234_BUSY_COUNT"] = str(count)
    LOGGER.warning(
        "KRAKEN_READ_LOCK_V234_STARVATION marker=%s busy_count=%d age_s=%.2f "
        "action=observe_fail_closed reset_requires_success=true lock_bypass=false "
        "local_contention=true broker_unavailability_unproven=true",
        MARKER, count, age,
    )


def _note_success() -> None:
    global _BUSY_SINCE, _LAST_BUSY, _BUSY_COUNT
    with _LOCK:
        had_episode = _BUSY_SINCE > 0.0
        _BUSY_SINCE = 0.0
        _LAST_BUSY = 0.0
        _BUSY_COUNT = 0
    os.environ.pop("NIJA_KRAKEN_READ_LOCK_V234_STARVING", None)
    os.environ.pop("NIJA_KRAKEN_READ_LOCK_V234_BUSY_COUNT", None)
    if had_episode:
        LOGGER.info(
            "KRAKEN_READ_LOCK_V234_RECOVERED marker=%s proof=successful_private_call "
            "recycle_cancelled=true synthetic_success=false",
            MARKER,
        )


def _patch_broker_manager(module: ModuleType | None = None) -> bool:
    module = module or sys.modules.get("bot.broker_manager") or sys.modules.get("broker_manager")
    if not isinstance(module, ModuleType):
        return True
    cls = getattr(module, "KrakenBroker", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "_kraken_private_call", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    @wraps(current)
    def kraken_private_call_v234(self: Any, *args: Any, **kwargs: Any):
        global _ACTIVE_MUTATIONS
        method = _method_from_call(args, kwargs)
        mutating = method in _MUTATING
        if mutating:
            with _LOCK:
                _ACTIVE_MUTATIONS += 1
            try:
                result = current(self, *args, **kwargs)
                _note_success()
                return result
            finally:
                with _LOCK:
                    _ACTIVE_MUTATIONS = max(0, _ACTIVE_MUTATIONS - 1)

        try:
            result = current(self, *args, **kwargs)
            _note_success()
            return result
        except BaseException as exc:
            if _is_lock_busy(exc):
                _note_busy()
            raise

    setattr(kraken_private_call_v234, _PATCH_ATTR, True)
    setattr(kraken_private_call_v234, "__wrapped__", current)
    cls._kraken_private_call = kraken_private_call_v234
    return True


def _watchdog() -> None:
    global _RECYCLE_REQUESTED
    while True:
        time.sleep(1.0)
        now = time.monotonic()
        with _LOCK:
            if _RECYCLE_REQUESTED:
                return
            if _BUSY_SINCE <= 0.0:
                continue
            age = now - _BUSY_SINCE
            count = _BUSY_COUNT
            active_mutations = _ACTIVE_MUTATIONS
            # Require both elapsed time and repeated independent failed reads.
            # Do not clear merely because probes are sparse; success owns reset.
            if age < _stale_after_s() or count < 3:
                continue
            if active_mutations > 0:
                LOGGER.critical(
                    "KRAKEN_READ_LOCK_V234_RECYCLE_DEFERRED marker=%s age_s=%.2f busy_count=%d "
                    "active_mutations=%d reason=mutation_inflight safety_preserved=true",
                    MARKER, age, count, active_mutations,
                )
                continue
            _RECYCLE_REQUESTED = True

        os.environ["NIJA_KRAKEN_READ_LOCK_V234_RECYCLE_REQUESTED"] = "1"
        LOGGER.critical(
            "KRAKEN_READ_LOCK_V234_RECYCLE_REQUESTED marker=%s age_s=%.2f busy_count=%d "
            "active_mutations=0 signal=SIGTERM lock_force_release=false balance_fabricated=false "
            "execution_authority_unchanged=true nonce_policy_unchanged=true order_retry=false "
            "local_contention=true broker_unavailability_unproven=true safety_gates_bypassed=false",
            MARKER, age, count,
        )
        try:
            os.kill(os.getpid(), signal.SIGTERM)
        except Exception as exc:
            LOGGER.error(
                "KRAKEN_READ_LOCK_V234_RECYCLE_SIGNAL_ERROR marker=%s error=%s:%s trading_fail_closed=true",
                MARKER, type(exc).__name__, exc,
            )
        return


def install() -> bool:
    global _STARTED
    with _LOCK:
        if not _patch_broker_manager():
            return False
        os.environ["NIJA_RUNTIME_KRAKEN_READ_LOCK_RECOVERY_V234_INSTALLED"] = "1"
        if not _STARTED:
            _STARTED = True
            threading.Thread(target=_watchdog, name="KrakenReadLockRecoveryV234", daemon=True).start()
    LOGGER.critical(
        "RUNTIME_KRAKEN_READ_LOCK_RECOVERY_V234_READY marker=%s ready=true "
        "recycle_after_s=%.2f quiet_reset_s=%.2f reset_requires_success=true "
        "process_local_lock_only=true mutating_calls_tracked=true lock_force_release=false "
        "lock_bypass=false balance_fabricated=false execution_authority_granted=false "
        "nonce_policy_unchanged=true local_contention_not_exchange_failure=true "
        "forced_trade=false safety_gates_bypassed=false",
        MARKER, _stale_after_s(), _quiet_reset_s(),
    )
    return True


__all__ = ["MARKER", "install", "_patch_broker_manager", "_stale_after_s", "_quiet_reset_s"]
