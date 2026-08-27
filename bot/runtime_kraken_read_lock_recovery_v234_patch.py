"""Recover from a permanently wedged process-local Kraken private-read lock.

v234 observes KrakenReadLockBusy at every live KrakenBroker class identity.  A local
read-lock timeout is not exchange/API/auth/nonce failure.  Reads remain fail-closed;
mutating calls are never retried or lock-bypassed.  If repeated local contention is
proven and no mutation is in flight, the process may recycle so the stale in-process
lock is discarded safely.
"""
from __future__ import annotations

import importlib
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
_MODULES = ("bot.broker_integration", "broker_integration", "bot.broker_manager", "broker_manager")
_MUTATING = {"AddOrder", "AddOrderBatch", "CancelOrder", "CancelOrderBatch", "CancelAll", "CancelAllOrdersAfter", "EditOrder"}


def _float_env(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _stale_after_s() -> float:
    return _float_env("NIJA_KRAKEN_READ_LOCK_RECYCLE_AFTER_S", 15.0, 10.0, 120.0)


def _quiet_reset_s() -> float:
    return _float_env("NIJA_KRAKEN_READ_LOCK_QUIET_RESET_S", 8.0, 3.0, 30.0)


def _method_from_call(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    return str(args[0] if args else kwargs.get("method", "") or "")


def _is_lock_busy(exc: BaseException) -> bool:
    try:
        from bot.kraken_read_timeout_v121_patch import KrakenReadLockBusy
        if isinstance(exc, KrakenReadLockBusy):
            return True
    except Exception:
        pass
    text = str(exc or "").lower()
    return "kraken read lock busy" in text or "krakenreadlockbusy" in text


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
    os.environ["NIJA_KRAKEN_READ_LOCK_V234_BUSY_EPOCH"] = str(time.time())
    LOGGER.warning(
        "KRAKEN_READ_LOCK_V234_STARVATION marker=%s busy_count=%d age_s=%.2f "
        "action=observe_fail_closed reset_requires_success=true lock_bypass=false local_contention=true "
        "broker_unavailability_unproven=true",
        MARKER, count, age,
    )


def _note_success() -> None:
    global _BUSY_SINCE, _LAST_BUSY, _BUSY_COUNT
    with _LOCK:
        had_episode = _BUSY_SINCE > 0.0
        _BUSY_SINCE = 0.0
        _LAST_BUSY = 0.0
        _BUSY_COUNT = 0
    for key in ("NIJA_KRAKEN_READ_LOCK_V234_STARVING", "NIJA_KRAKEN_READ_LOCK_V234_BUSY_COUNT", "NIJA_KRAKEN_READ_LOCK_V234_BUSY_EPOCH"):
        os.environ.pop(key, None)
    if had_episode:
        LOGGER.info("KRAKEN_READ_LOCK_V234_RECOVERED marker=%s proof=successful_private_call recycle_cancelled=true synthetic_success=false", MARKER)


def _patch_class(cls: type) -> bool:
    current = getattr(cls, "_kraken_private_call", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
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
        except BaseException as exc:
            if _is_lock_busy(exc):
                _note_busy()
            raise
        finally:
            if mutating:
                with _LOCK:
                    _ACTIVE_MUTATIONS = max(0, _ACTIVE_MUTATIONS - 1)

    setattr(kraken_private_call_v234, _PATCH_ATTR, True)
    setattr(kraken_private_call_v234, "__wrapped__", current)
    cls._kraken_private_call = kraken_private_call_v234
    return True


def _patch_all_kraken_classes() -> tuple[bool, int, tuple[str, ...]]:
    classes: dict[int, type] = {}
    modules: list[str] = []
    canonical_manager_found = False
    for name in _MODULES:
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            try:
                module = importlib.import_module(name)
            except Exception:
                continue
        cls = getattr(module, "KrakenBroker", None)
        if isinstance(cls, type):
            classes[id(cls)] = cls
            module_name = str(getattr(module, "__name__", name))
            modules.append(module_name)
            # ``KrakenBroker`` is defined by the canonical broker-manager
            # module.  ``bot.broker_integration`` exposes
            # ``KrakenBrokerAdapter`` instead, so requiring a KrakenBroker
            # class there makes this installer permanently report false even
            # after the real live class has been patched.
            if module_name == "bot.broker_manager":
                canonical_manager_found = True
    patched = sum(1 for cls in classes.values() if _patch_class(cls))
    return bool(classes and canonical_manager_found and patched == len(classes)), patched, tuple(sorted(set(modules)))


def _patch_broker_manager(module: ModuleType | None = None) -> bool:
    # Backward-compatible entrypoint retained for older convergence callers.
    ready, _, _ = _patch_all_kraken_classes()
    return ready


def _install_v235() -> bool:
    try:
        module = importlib.import_module("bot.runtime_heartbeat_terminal_broker_manager_v235_patch")
        installer = getattr(module, "install", None)
        return bool(installer()) if callable(installer) else False
    except Exception as exc:
        LOGGER.error("HEARTBEAT_TERMINAL_BROKER_MANAGER_V235_CHAIN_INSTALL_ERROR marker=%s error=%s:%s trading_fail_closed=true", MARKER, type(exc).__name__, exc)
        return False


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
            if age < _stale_after_s() or count < 3:
                continue
            if active_mutations > 0:
                LOGGER.critical("KRAKEN_READ_LOCK_V234_RECYCLE_DEFERRED marker=%s age_s=%.2f busy_count=%d active_mutations=%d reason=mutation_inflight safety_preserved=true", MARKER, age, count, active_mutations)
                continue
            _RECYCLE_REQUESTED = True
        os.environ["NIJA_KRAKEN_READ_LOCK_V234_RECYCLE_REQUESTED"] = "1"
        LOGGER.critical("KRAKEN_READ_LOCK_V234_RECYCLE_REQUESTED marker=%s age_s=%.2f busy_count=%d active_mutations=0 signal=SIGTERM lock_force_release=false balance_fabricated=false execution_authority_unchanged=true nonce_policy_unchanged=true order_retry=false local_contention=true broker_unavailability_unproven=true safety_gates_bypassed=false", MARKER, age, count)
        try:
            os.kill(os.getpid(), signal.SIGTERM)
        except Exception as exc:
            LOGGER.error("KRAKEN_READ_LOCK_V234_RECYCLE_SIGNAL_ERROR marker=%s error=%s:%s trading_fail_closed=true", MARKER, type(exc).__name__, exc)
        return


def install() -> bool:
    global _STARTED
    with _LOCK:
        aliases_ready, patched_classes, modules = _patch_all_kraken_classes()
        if not aliases_ready:
            return False
        if not _install_v235():
            LOGGER.error("RUNTIME_KRAKEN_READ_LOCK_RECOVERY_V234_V235_NOT_READY marker=%s trading_fail_closed=true", MARKER)
            return False
        os.environ["NIJA_RUNTIME_KRAKEN_READ_LOCK_RECOVERY_V234_INSTALLED"] = "1"
        if not _STARTED:
            _STARTED = True
            threading.Thread(target=_watchdog, name="KrakenReadLockRecoveryV234", daemon=True).start()
    LOGGER.critical(
        "RUNTIME_KRAKEN_READ_LOCK_RECOVERY_V234_READY marker=%s ready=true patched_classes=%d modules=%s "
        "live_broker_integration_required=true recycle_after_s=%.2f quiet_reset_s=%.2f reset_requires_success=true "
        "process_local_lock_only=true mutating_calls_tracked=true lock_force_release=false lock_bypass=false "
        "balance_fabricated=false execution_authority_granted=false nonce_policy_unchanged=true "
        "local_contention_not_exchange_failure=true heartbeat_terminal_v235=true forced_trade=false safety_gates_bypassed=false",
        MARKER, patched_classes, ",".join(modules), _stale_after_s(), _quiet_reset_s(),
    )
    return True


__all__ = ["MARKER", "install", "_patch_broker_manager", "_patch_all_kraken_classes", "_stale_after_s", "_quiet_reset_s", "_install_v235"]
