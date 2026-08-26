"""Recover from a permanently wedged process-local Kraken private-read lock.

Production on 2026-08-26 proved that v212's bounded 3 s lock admission correctly
fails closed, but a process-local lock can remain unavailable across many
successive reads (99+ observed). Because ``threading`` locks cannot be safely
force-released by a non-owner thread, the only safe automatic recovery for a
stale in-process owner is to recycle the worker process after a bounded grace
period.

This patch does NOT bypass the Kraken lock, fabricate balances, clear the kill
switch, grant execution authority, change nonce policy, or retry mutating calls.
It observes consecutive ``KrakenReadLockBusy`` failures from the existing v121
wrapper. If the canonical Kraken read lock remains continuously unavailable for
at least the configured stale interval and there is no tracked mutating Kraken
private call in flight, it sends SIGTERM to the current process so the service
supervisor can start a clean process with a fresh process-local lock.

Mutating calls remain serialized by the original broker implementation. A
mutating call resets/suppresses recovery while active, preventing a recycle from
being initiated by this patch during a known order/cancel/edit request.
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
    "AddOrder",
    "AddOrderBatch",
    "CancelOrder",
    "CancelOrderBatch",
    "CancelAll",
    "CancelAllOrdersAfter",
    "EditOrder",
}


def _float_env(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _stale_after_s() -> float:
    # Long enough to distinguish ordinary serialized Kraken activity from the
    # sustained 99+ failure lock starvation observed in production.
    return _float_env("NIJA_KRAKEN_READ_LOCK_RECYCLE_AFTER_S", 30.0, 15.0, 120.0)


def _quiet_reset_s() -> float:
    # A successful/quiet interval clears the consecutive-starvation episode.
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
    text = str(exc or "").lower()
    return "kraken read lock busy" in text


def _note_busy() -> None:
    global _BUSY_SINCE, _LAST_BUSY, _BUSY_COUNT
    now = time.monotonic()
    with _LOCK:
        if _BUSY_SINCE <= 0.0 or (now - _LAST_BUSY) > _quiet_reset_s():
            _BUSY_SINCE = now
            _BUSY_COUNT = 0
        _LAST_BUSY = now
        _BUSY_COUNT += 1
        count = _BUSY_COUNT
        age = max(0.0, now - _BUSY_SINCE)
    LOGGER.warning(
        "KRAKEN_READ_LOCK_V234_STARVATION marker=%s busy_count=%d age_s=%.2f "
        "action=observe_fail_closed mutating_calls_unchanged=true lock_bypass=false",
        MARKER,
        count,
        age,
    )


def _note_success() -> None:
    global _BUSY_SINCE, _LAST_BUSY, _BUSY_COUNT
    with _LOCK:
        _BUSY_SINCE = 0.0
        _LAST_BUSY = 0.0
        _BUSY_COUNT = 0


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
    global _RECYCLE_REQUESTED, _BUSY_SINCE, _LAST_BUSY, _BUSY_COUNT
    while True:
        time.sleep(1.0)
        now = time.monotonic()
        with _LOCK:
            if _RECYCLE_REQUESTED:
                return
            if _BUSY_SINCE <= 0.0:
                continue
            # If contention stopped, clear the episode without action.
            if _LAST_BUSY > 0.0 and (now - _LAST_BUSY) > _quiet_reset_s():
                _BUSY_SINCE = 0.0
                _LAST_BUSY = 0.0
                _BUSY_COUNT = 0
                continue
            age = now - _BUSY_SINCE
            count = _BUSY_COUNT
            active_mutations = _ACTIVE_MUTATIONS
            if age < _stale_after_s() or count < 3:
                continue
            if active_mutations > 0:
                LOGGER.critical(
                    "KRAKEN_READ_LOCK_V234_RECYCLE_DEFERRED marker=%s age_s=%.2f busy_count=%d "
                    "active_mutations=%d reason=mutation_inflight safety_preserved=true",
                    MARKER,
                    age,
                    count,
                    active_mutations,
                )
                continue
            _RECYCLE_REQUESTED = True

        # A process-local lock owned by a wedged/dead thread cannot be safely
        # force-released from here. Controlled process recycle is the recovery.
        os.environ["NIJA_KRAKEN_READ_LOCK_V234_RECYCLE_REQUESTED"] = "1"
        LOGGER.critical(
            "KRAKEN_READ_LOCK_V234_RECYCLE_REQUESTED marker=%s age_s=%.2f busy_count=%d "
            "active_mutations=0 signal=SIGTERM lock_force_release=false balance_fabricated=false "
            "execution_authority_unchanged=true nonce_policy_unchanged=true order_retry=false "
            "safety_gates_bypassed=false",
            MARKER,
            age,
            count,
        )
        try:
            os.kill(os.getpid(), signal.SIGTERM)
        except Exception as exc:
            LOGGER.error(
                "KRAKEN_READ_LOCK_V234_RECYCLE_SIGNAL_ERROR marker=%s error=%s:%s "
                "trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
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
            threading.Thread(
                target=_watchdog,
                name="KrakenReadLockRecoveryV234",
                daemon=True,
            ).start()
    LOGGER.critical(
        "RUNTIME_KRAKEN_READ_LOCK_RECOVERY_V234_READY marker=%s ready=true "
        "recycle_after_s=%.2f quiet_reset_s=%.2f process_local_lock_only=true "
        "mutating_calls_tracked=true lock_force_release=false lock_bypass=false "
        "balance_fabricated=false execution_authority_granted=false nonce_policy_unchanged=true "
        "forced_trade=false safety_gates_bypassed=false",
        MARKER,
        _stale_after_s(),
        _quiet_reset_s(),
    )
    return True


__all__ = ["MARKER", "install", "_patch_broker_manager", "_stale_after_s", "_quiet_reset_s"]
