"""Runtime refresh-demand convergence v167.

Attests the pre-bootstrap v32 refresh-demand repair and keeps it installed after
late imports. Routine capital freshness belongs to v137 once that scheduler is
available; genuine reconnect/recovery triggers retain authoritative refreshes.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from typing import Any

LOGGER = logging.getLogger("nija.runtime_refresh_demand_v167")
MARKER = "20260819-runtime-refresh-demand-v167"
_READY_FLAG = "NIJA_RUNTIME_REFRESH_DEMAND_V167_READY"
_LOCK = threading.RLock()


def _v32() -> Any:
    return importlib.import_module("bot.runtime_execution_convergence_v32")


def _verify_v32() -> bool:
    module = _v32()
    reconcile = getattr(module, "_request_runtime_reconciliation", None)
    monitor = getattr(module, "_monitor", None)
    owner = getattr(module, "_routine_refresh_owned_by_v137", None)
    startup = getattr(module, "_startup_runtime_refresh_ready", None)
    return bool(
        callable(reconcile)
        and bool(getattr(reconcile, "_nija_runtime_refresh_demand_v167", False))
        and callable(monitor)
        and callable(owner)
        and callable(startup)
    )


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_refresh_demand_v167"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        try:
            module = _v32()
            installer = getattr(module, "install", None)
            if callable(installer):
                installer()
        except Exception as exc:
            LOGGER.error(
                "RUNTIME_REFRESH_DEMAND_V167_V32_INSTALL_ERROR marker=%s error=%s:%s",
                MARKER,
                type(exc).__name__,
                exc,
            )
        verified = _verify_v32()
        manifest_ok = _patch_release_manifest()
        ready = bool(verified and manifest_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "RUNTIME_REFRESH_DEMAND_V167_FAILED marker=%s v32_verified=%s manifest_ok=%s "
                "trading_fail_closed=true",
                MARKER,
                str(verified).lower(),
                str(manifest_ok).lower(),
            )
            return False
        LOGGER.critical(
            "RUNTIME_REFRESH_DEMAND_V167 marker=%s ready=true startup_double_refresh_removed=true "
            "monitor_initial_delay=true routine_refresh_owner=v137 recovery_refresh_preserved=true "
            "publication_expiry_extended=false stale_promoted=false safety_gates_bypassed=false",
            MARKER,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = ["MARKER", "install", "install_import_hook", "_verify_v32"]
