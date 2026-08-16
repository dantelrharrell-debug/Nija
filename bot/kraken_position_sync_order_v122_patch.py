"""Require bounded Kraken reads before platform position-sync dispatch.

Production 0919a4ad showed a startup-order race: v98 installed v108 before v121.
That allowed v108 to dispatch a Kraken position worker before the v121 wrapper
could apply the supported krakenex HTTP timeout.  If that first private Balance
request stalled while holding the shared Kraken API lock, later bounded
position-fetch generations could only queue behind the already-unbounded call.

v122 closes the race without changing position truth or activation policy:
* v121 must be installed before this guard installs;
* Kraken platform position dispatch is suppressed unless the v121 install flag
  remains present;
* Coinbase/OKX dispatch is unchanged;
* no synthetic position snapshot or readiness is published;
* release attestation includes v122.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.kraken_position_sync_order_v122")
MARKER = "20260816-kraken-position-sync-order-v122"
RELEASE_ID = "20260816-runtime-convergence-v122"
_PATCH_ATTR = "_nija_kraken_position_sync_order_v122"
_LOCK = threading.RLock()


def _timeout_layer_ready() -> bool:
    return os.environ.get("NIJA_KRAKEN_READ_TIMEOUT_V121_INSTALLED", "") == "1"


def _patch_v108() -> bool:
    try:
        from bot import platform_position_sync_v108_patch as v108
    except Exception:
        return False

    current = getattr(v108, "_connected_unsynced_platform_brokers", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    @wraps(current)
    def guarded(manager: Any):
        found = list(current(manager) or [])
        if _timeout_layer_ready():
            return found
        kept = []
        blocked = 0
        for broker_name, broker in found:
            if str(broker_name or "").lower() == "kraken":
                blocked += 1
                continue
            kept.append((broker_name, broker))
        if blocked:
            LOGGER.critical(
                "KRAKEN_POSITION_SYNC_V122_DISPATCH_BLOCKED marker=%s blocked=%d reason=v121_timeout_layer_missing trading_fail_closed=true synthetic_empty_snapshot=false",
                MARKER,
                blocked,
            )
        return kept

    setattr(guarded, _PATCH_ATTR, True)
    setattr(guarded, "__wrapped__", current)
    v108._connected_unsynced_platform_brokers = guarded
    LOGGER.critical(
        "KRAKEN_POSITION_SYNC_V122_V108_GUARD_PATCHED marker=%s v121_required=true coinbase_okx_unchanged=true synthetic_empty_snapshot=false",
        MARKER,
    )
    return True


def _patch_release_manifest() -> bool:
    manifest = sys.modules.get("bot.runtime_release_manifest_patch") or sys.modules.get(
        "runtime_release_manifest_patch"
    )
    if not isinstance(manifest, ModuleType):
        try:
            import bot.runtime_release_manifest_patch as manifest  # type: ignore[no-redef]
        except Exception:
            return False
    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    if not isinstance(required, dict):
        return False
    required["kraken_position_sync_order_v122"] = "NIJA_KRAKEN_POSITION_SYNC_ORDER_V122_INSTALLED"
    manifest.RELEASE_ID = RELEASE_ID
    return True


def install() -> bool:
    with _LOCK:
        if not _timeout_layer_ready():
            LOGGER.critical(
                "KRAKEN_POSITION_SYNC_V122_INSTALL_BLOCKED marker=%s reason=v121_timeout_layer_missing trading_fail_closed=true",
                MARKER,
            )
            return False
        if not _patch_v108():
            return False
        os.environ["NIJA_KRAKEN_POSITION_SYNC_ORDER_V122_INSTALLED"] = "1"
        if not _patch_release_manifest():
            os.environ.pop("NIJA_KRAKEN_POSITION_SYNC_ORDER_V122_INSTALLED", None)
            return False
        LOGGER.critical(
            "KRAKEN_POSITION_SYNC_ORDER_V122_INSTALLED marker=%s v121_precedes_v108=true first_kraken_private_read_bounded=true activation_gates_unchanged=true",
            MARKER,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_timeout_layer_ready",
    "_patch_v108",
]
