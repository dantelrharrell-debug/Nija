"""Kraken protective-order persistence guard v397.

Prevents NIJA native stop-loss/take-profit orphan cleanup from cancelling
protective orders on a transient or partial Kraken margin visibility event.

Safety contract:
* If any authenticated Kraken margin exposure exists for the account, cancel no
  NIJA native protective orders at all.
* If authenticated OpenPositions is empty, require three consecutive successful
  empty-margin reconcile cycles before v380 orphan cleanup may run.
* Any non-empty exposure resets the absence counter immediately.
* Failed OpenPositions reads never advance the counter because v380 only calls
  cleanup after a successful authenticated fetch.
* Order submission, reduce-only semantics, writer/nonce/rate gates, and manual
  orders are unchanged.
"""
from __future__ import annotations

import importlib
import logging
import threading
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_kraken_protective_order_persistence_v397")
MARKER = "20260907-kraken-protective-order-persistence-v397"
_PATCH_ATTR = "_nija_kraken_protective_order_persistence_v397"
_LOCK = threading.RLock()
_EMPTY_STREAK: dict[str, int] = {}
_REQUIRED_EMPTY_PROOFS = 3


def _v380():
    return importlib.import_module("bot.runtime_kraken_native_margin_backup_v380_patch")


def install() -> bool:
    module = _v380()
    current = getattr(module, "_cleanup_orphans", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def cleanup_orphans_v397(account: str, broker: Any, active_symbols: set[str]):
        key = str(account)
        symbols = {str(item) for item in set(active_symbols or set()) if str(item)}
        with _LOCK:
            if symbols:
                _EMPTY_STREAK[key] = 0
                LOGGER.critical(
                    "KRAKEN_PROTECTIVE_ORDER_PERSISTENCE_V397_HOLD marker=%s account=%s "
                    "active_symbols=%s reason=authenticated_exposure_present cancellations_blocked=true "
                    "stop_loss_preserved=true take_profit_preserved=true replacement_required_before_cancel=true "
                    "safety_gates_bypassed=false",
                    MARKER, key, tuple(sorted(symbols)),
                )
                return ()
            streak = int(_EMPTY_STREAK.get(key, 0) or 0) + 1
            _EMPTY_STREAK[key] = streak
        if streak < _REQUIRED_EMPTY_PROOFS:
            LOGGER.critical(
                "KRAKEN_PROTECTIVE_ORDER_PERSISTENCE_V397_DEFER marker=%s account=%s "
                "empty_proof_streak=%d required=%d cancellations_blocked=true "
                "single_absence_not_closure_proof=true stop_loss_preserved=true take_profit_preserved=true "
                "safety_gates_bypassed=false",
                MARKER, key, streak, _REQUIRED_EMPTY_PROOFS,
            )
            return ()
        cancelled = original(account, broker, active_symbols)
        LOGGER.critical(
            "KRAKEN_PROTECTIVE_ORDER_PERSISTENCE_V397_RELEASE marker=%s account=%s "
            "empty_proof_streak=%d required=%d cancelled=%s repeated_authenticated_absence_required=true "
            "safety_gates_bypassed=false",
            MARKER, key, streak, _REQUIRED_EMPTY_PROOFS, tuple(cancelled or ()),
        )
        return cancelled

    cleanup_orphans_v397.__name__ = "cleanup_orphans_v397"
    setattr(cleanup_orphans_v397, _PATCH_ATTR, True)
    setattr(cleanup_orphans_v397, "__wrapped__", original)
    module._cleanup_orphans = cleanup_orphans_v397
    LOGGER.critical(
        "RUNTIME_KRAKEN_PROTECTIVE_ORDER_PERSISTENCE_V397_READY marker=%s "
        "active_exposure_cancel_block=true empty_proofs_required=%d transient_absence_safe=true "
        "manual_orders_unchanged=true order_submission_unchanged=true safety_gates_bypassed=false",
        MARKER, _REQUIRED_EMPTY_PROOFS,
    )
    return True


def install_import_hook() -> bool:
    return install()


__all__ = ["MARKER", "install", "install_import_hook"]
