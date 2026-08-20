"""Runtime refresh-demand convergence v167.

Attests the pre-bootstrap v32 refresh-demand repair and keeps it installed after
late imports. Routine capital freshness belongs to v137 once that scheduler is
available; genuine reconnect/recovery triggers retain authoritative refreshes.

If the legacy periodic runtime-convergence path ever has to fall back because
v137 is unavailable, classify that refresh as proactive for v166 timing so it
uses the same bounded 30s fetch / 50s total runtime budget instead of reopening
the older 80s coordinator path.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_refresh_demand_v167")
MARKER = "20260819-runtime-refresh-demand-v167"
_READY_FLAG = "NIJA_RUNTIME_REFRESH_DEMAND_V167_READY"
_PATCH_ATTR = "_nija_runtime_refresh_demand_v167"
_LOCK = threading.RLock()


def _v32() -> Any:
    return importlib.import_module("bot.runtime_execution_convergence_v32")


def _v166() -> Any:
    return importlib.import_module("bot.runtime_capital_refresh_ownership_v166_patch")


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


def _patch_v166_periodic_fallback() -> bool:
    """Keep any periodic fallback inside the proactive v166 runtime budget."""
    try:
        v166 = _v166()
    except Exception:
        return False
    current = getattr(v166, "_is_proactive_trigger", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def proactive_v167(value: Any = None) -> bool:
        if value is None:
            try:
                trigger = str(getattr(v166, "_trigger")() or "").strip().lower()
            except Exception:
                trigger = ""
        else:
            trigger = str(value or "").strip().lower()
        if trigger == "periodic_runtime_convergence" or trigger.startswith(
            "periodic_runtime_convergence:"
        ):
            return True
        return bool(original(value))

    setattr(proactive_v167, _PATCH_ATTR, True)
    setattr(proactive_v167, "__wrapped__", original)
    v166._is_proactive_trigger = proactive_v167
    return True


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
        periodic_ok = _patch_v166_periodic_fallback()
        manifest_ok = _patch_release_manifest()
        ready = bool(verified and periodic_ok and manifest_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "RUNTIME_REFRESH_DEMAND_V167_FAILED marker=%s v32_verified=%s periodic_fallback_ok=%s "
                "manifest_ok=%s trading_fail_closed=true",
                MARKER,
                str(verified).lower(),
                str(periodic_ok).lower(),
                str(manifest_ok).lower(),
            )
            return False
        LOGGER.critical(
            "RUNTIME_REFRESH_DEMAND_V167 marker=%s ready=true startup_double_refresh_removed=true "
            "monitor_initial_delay=true routine_refresh_owner=v137 periodic_fallback_bounded=true "
            "recovery_refresh_preserved=true publication_expiry_extended=false stale_promoted=false "
            "safety_gates_bypassed=false",
            MARKER,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_verify_v32",
    "_patch_v166_periodic_fallback",
]
