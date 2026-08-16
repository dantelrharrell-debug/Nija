"""Install Kraken read timeout before platform position dispatch.

Production v121 remained fail-closed but exposed an ordering race: v98 installed
platform position sync v108 before the Kraken HTTP timeout layer v121.  v108 can
patch capital refresh immediately and dispatch a Kraken position worker before
v121 wraps the concrete krakenex API object.  That first read can then hold the
shared Kraken API lock indefinitely even though later generations are bounded.

v122 closes the race without weakening readiness:
* install v121 before v108 is allowed to dispatch Kraken reconciliation;
* wrap v108 discovery so Kraken is omitted unless the v121 installed flag is
  present;
* leave Coinbase/OKX discovery unchanged;
* do not synthesize positions/readiness and do not alter writer, nonce, risk,
  capital, or execution gates.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.kraken_timeout_order_v122")
MARKER = "20260816-kraken-timeout-order-v122"
RELEASE_ID = "20260816-runtime-convergence-v122"
_PATCH_ATTR = "_nija_kraken_timeout_order_v122"
_LOCK = threading.RLock()


def _timeout_layer_ready() -> bool:
    return os.environ.get("NIJA_KRAKEN_READ_TIMEOUT_V121_INSTALLED", "0") == "1"


def _install_v121() -> bool:
    try:
        from bot import kraken_read_timeout_v121_patch as v121
    except ImportError:
        import kraken_read_timeout_v121_patch as v121  # type: ignore[import]
    installer = getattr(v121, "install", None) or getattr(v121, "install_import_hook", None)
    return bool(callable(installer) and installer() is not False and _timeout_layer_ready())


def _patch_v108() -> bool:
    try:
        from bot import platform_position_sync_v108_patch as v108
    except ImportError:
        import platform_position_sync_v108_patch as v108  # type: ignore[import]

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
            if str(broker_name or "").strip().lower() == "kraken":
                blocked += 1
                continue
            kept.append((broker_name, broker))
        if blocked:
            LOGGER.critical(
                "KRAKEN_TIMEOUT_ORDER_V122_DISPATCH_BLOCKED marker=%s kraken_workers_blocked=%d reason=v121_not_installed trading_fail_closed=true",
                MARKER,
                blocked,
            )
        return kept

    setattr(guarded, _PATCH_ATTR, True)
    setattr(guarded, "__wrapped__", current)
    v108._connected_unsynced_platform_brokers = guarded
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
    required["kraken_timeout_order_v122"] = "NIJA_KRAKEN_TIMEOUT_ORDER_V122_INSTALLED"
    manifest.RELEASE_ID = RELEASE_ID
    return True


def install() -> bool:
    with _LOCK:
        if not _install_v121():
            LOGGER.critical(
                "KRAKEN_TIMEOUT_ORDER_V122_V121_INSTALL_FAILED marker=%s trading_fail_closed=true",
                MARKER,
            )
            return False
        if not _patch_v108():
            return False
        os.environ["NIJA_KRAKEN_TIMEOUT_ORDER_V122_INSTALLED"] = "1"
        if not _patch_release_manifest():
            os.environ.pop("NIJA_KRAKEN_TIMEOUT_ORDER_V122_INSTALLED", None)
            return False
        LOGGER.critical(
            "KRAKEN_TIMEOUT_ORDER_V122_INSTALLED marker=%s v121_before_v108=true kraken_dispatch_requires_timeout_layer=true synthetic_empty_snapshot=false safety_gates_unchanged=true",
            MARKER,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = ["MARKER", "RELEASE_ID", "install", "install_import_hook", "_timeout_layer_ready"]
