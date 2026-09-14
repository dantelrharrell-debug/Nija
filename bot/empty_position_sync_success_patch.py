"""Preserve successful empty-position snapshots without refetching brokers.

The canonical startup reconciler already marks a connected broker synchronized
when its authoritative ``get_positions()`` call succeeds with an empty list.
This compatibility patch therefore must not issue a second broker fetch: an
outer runtime wrapper may intentionally convert a failed inner fetch to ``[]``
for balance/equity classification, and treating that fallback as authoritative
would incorrectly turn a timeout into synchronization success.

September 14, 2026 liveness repair:
Install the broker-object identity selector used by all-account coverage as soon
as this early startup patch runs.  Kraken user reconnect can temporarily leave a
retired broker object in one compatibility registry while the authenticated
replacement is already present in another.  Position-readiness must inspect the
best already-existing canonical broker object for that account instead of
waiting for the later full v374 convergence chain.  The v374 selector performs
no broker I/O, does not mutate manager registries, and does not fabricate
connectivity, positions, balances, readiness, or execution authority.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.empty_position_sync_success")
_MARKER = "20260815-empty-position-sync-v2"
_EARLY_IDENTITY_MARKER = "20260914-early-user-broker-identity-v417"
_ATTR = "_nija_empty_position_sync_success_v2"
_LOCK = threading.RLock()


def _patch(module: ModuleType) -> bool:
    current = getattr(module, "_adopt_broker_positions", None)
    if not callable(current):
        return False
    if getattr(current, _ATTR, False):
        return True

    @wraps(current)
    def adopt(broker: Any, broker_name: str, eps: Any) -> int:
        # Delegate exactly once to the canonical reconciler. It owns the
        # authoritative fetch and already treats a genuine empty snapshot as
        # synchronized. Never refetch here and never manufacture success from
        # a compatibility-layer empty fallback.
        result = int(current(broker, broker_name, eps) or 0)
        fetch_ok = getattr(broker, "_startup_position_sync_fetch_ok", None)
        if fetch_ok is False:
            setattr(broker, "_startup_position_sync_adopted", False)
            logger.warning(
                "EMPTY_POSITION_SYNC_FAILURE_PRESERVED marker=%s broker=%s error=%s authoritative_empty=false",
                _MARKER,
                broker_name,
                getattr(broker, "_startup_position_sync_error", "position_fetch_failed"),
            )
        return result

    setattr(adopt, _ATTR, True)
    adopt.__wrapped__ = current
    module._adopt_broker_positions = adopt
    os.environ["NIJA_EMPTY_POSITION_SYNC_READY"] = "1"
    logger.critical(
        "EMPTY_POSITION_SYNC_SUCCESS_PATCHED marker=%s refetch=false masked_failure_preserved=true",
        _MARKER,
    )
    return True


def _install_early_user_broker_identity() -> bool:
    """Reassert only v374's no-I/O broker-object selector at early startup.

    This is deliberately narrower than installing the complete v374 chain.  It
    only patches v281's account denominator so duplicate user-account registry
    entries resolve to the strongest existing broker object.  All position,
    balance, snapshot-freshness, cost-basis, protection and execution gates
    remain unchanged and are still evaluated by their canonical owners.
    """
    try:
        identity = importlib.import_module(
            "bot.runtime_all_account_broker_identity_convergence_v374_patch"
        )
        patch = getattr(identity, "_patch_v281", None)
        if not callable(patch):
            raise RuntimeError("v374_identity_selector_unavailable")
        ready = bool(patch())
        if not ready:
            raise RuntimeError("v374_identity_selector_not_ready")
        os.environ["NIJA_EARLY_USER_BROKER_IDENTITY_V417_READY"] = "1"
        logger.critical(
            "EARLY_USER_BROKER_IDENTITY_V417_READY marker=%s "
            "v374_expected_account_selector=true broker_io=false registry_mutation=false "
            "snapshot_ttl_unchanged=true readiness_granted=false execution_proof_fabricated=false "
            "forced_trade=false safety_gates_bypassed=false",
            _EARLY_IDENTITY_MARKER,
        )
        return True
    except Exception as exc:
        os.environ["NIJA_EARLY_USER_BROKER_IDENTITY_V417_READY"] = "0"
        logger.warning(
            "EARLY_USER_BROKER_IDENTITY_V417_PENDING marker=%s error=%s:%s "
            "fail_closed=true readiness_granted=false safety_gates_bypassed=false",
            _EARLY_IDENTITY_MARKER,
            type(exc).__name__,
            exc,
        )
        return False


def install_import_hook() -> None:
    with _LOCK:
        module = importlib.import_module("bot.startup_position_sync")
        if not _patch(module):
            raise RuntimeError("startup_position_sync_not_patchable")
        # Identity convergence is a liveness repair only. Failure here must not
        # weaken position truth; later canonical v374 installation will retry it.
        _install_early_user_broker_identity()
        os.environ["NIJA_EMPTY_POSITION_SYNC_PATCH_INSTALLED"] = "1"


def install() -> None:
    install_import_hook()


__all__ = [
    "install",
    "install_import_hook",
    "_patch",
    "_install_early_user_broker_identity",
]
