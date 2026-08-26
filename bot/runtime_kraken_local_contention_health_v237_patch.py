"""Keep process-local Kraken read-lock contention out of broker failure health (v237).

Production on 2026-08-26 showed KrakenReadLockBusy causing user/platform broker
failure streaks and EXIT-ONLY even though v184/v234 classify the condition as local
process contention, not an authenticated Kraken/exchange failure.

v237 patches BrokerFailureManager.record_error only for Kraken errors whose reason is
an exact local read-lock contention signature. Those observations remain fail-closed
for the current read and are still handled by v234's bounded process recycle. They do
not increment exchange/account failure streaks or mark Kraken dead. All genuine API,
authentication, nonce, order, timeout, HTTP, and unattributed errors continue through
the original failure manager unchanged.
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
            LOGGER.warning(
                "KRAKEN_LOCAL_CONTENTION_V237_EXCLUDED marker=%s broker=%s "
                "reason=%s current_read_fail_closed=true broker_failure_streak_unchanged=true "
                "exchange_unavailability_unproven=true v234_recovery_authoritative=true "
                "auth_nonce_order_http_errors_unchanged=true safety_gates_bypassed=false",
                MARKER, broker_name, str(reason)[:160],
            )
            return False
        return bool(current(self, broker_name, reason))

    setattr(record_error_v237, _PATCH_ATTR, True)
    setattr(record_error_v237, "__wrapped__", current)
    cls.record_error = record_error_v237
    return True


def install() -> bool:
    try:
        v234 = importlib.import_module("bot.runtime_kraken_read_lock_recovery_v234_patch")
        installer = getattr(v234, "install", None)
        v234_ready = bool(callable(installer) and installer())
        patched = _patch_failure_manager()
        ready = bool(v234_ready and patched)
    except Exception as exc:
        LOGGER.error(
            "KRAKEN_LOCAL_CONTENTION_V237_INSTALL_ERROR marker=%s error=%s:%s trading_fail_closed=true",
            MARKER, type(exc).__name__, exc,
        )
        ready = False
    os.environ[_FLAG] = "1" if ready else "0"
    if ready:
        LOGGER.critical(
            "KRAKEN_LOCAL_CONTENTION_V237_READY marker=%s ready=true "
            "local_read_lock_only=true broker_failure_streak_excluded=true v234_required=true "
            "current_read_fail_closed=true genuine_exchange_errors_unchanged=true "
            "execution_authority_unchanged=true nonce_policy_unchanged=true forced_trade=false "
            "safety_gates_bypassed=false",
            MARKER,
        )
    return ready


def install_import_hook() -> bool:
    return install()


__all__ = ["MARKER", "install", "install_import_hook", "_is_local_contention"]
