"""Recover stale platform position snapshots through v108 without weakening v285 truth.

Production 2026-09-04 showed platform:kraken remaining stale while v285 repeatedly
requested recovery with ``platform_refresh_workers=0``. v285 correctly treats an
adopted-but-stale authoritative snapshot as not ready, but its recovery path calls
``v108.dispatch_platform_position_sync``. v108's legacy discovery only checks the
startup adoption latch and can therefore skip a broker whose v285 snapshot expired.

v355 makes v108 discovery use v285's stronger platform candidate predicate. It also
proves that the *exact* v355 discovery wrapper is the active outer owner instead of
trusting a marker that ``functools.wraps`` may copy to later foreign wrappers. A
small daemon monitor reasserts only this discovery wrapper if later runtime wrapper
churn displaces it. This preserves the existing v108 worker, 90s freshness TTL,
authoritative fetch requirement, v98 adoption path, single-flight worker and retry
bounds.

No position/capital/readiness/fill is fabricated. No TTL is extended, no stale
snapshot is promoted, no order is forced, and no kill switch or rejection latch is
changed.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_platform_stale_snapshot_recovery_v355")
MARKER = "20260904-runtime-platform-stale-snapshot-recovery-v355"
RELEASE_ID = "20260904-runtime-convergence-v355"
_READY_FLAG = "NIJA_RUNTIME_PLATFORM_STALE_SNAPSHOT_RECOVERY_V355_READY"
_PATCH_ATTR = "_nija_runtime_platform_stale_snapshot_recovery_v355"
_LOCK = threading.RLock()
_MONITOR_STARTED = False
_MONITOR_INTERVAL_S = 2.0


def _v108() -> Any:
    return importlib.import_module("bot.platform_position_sync_v108_patch")


def _v285() -> Any:
    return importlib.import_module("bot.runtime_authoritative_position_coverage_v285_patch")


def _is_exact_discovery(candidate: Any) -> bool:
    """Prove the active discovery callable is owned by this v355 module.

    A boolean marker alone is insufficient because ``functools.wraps`` copies a
    wrapped function's ``__dict__``. Later wrappers can therefore inherit the v355
    marker while implementing different discovery semantics.
    """
    if not callable(candidate) or not bool(getattr(candidate, _PATCH_ATTR, False)):
        return False
    owner = getattr(candidate, "__globals__", {}) or {}
    return bool(
        str(owner.get("MARKER", "")) == MARKER
        and str(owner.get("__name__", "")).endswith("runtime_platform_stale_snapshot_recovery_v355_patch")
        and str(getattr(candidate, "__name__", "")) == "discovery_v355"
    )


def _patch_discovery() -> bool:
    v108 = _v108()
    current = getattr(v108, "_connected_unsynced_platform_brokers", None)
    if not callable(current):
        return False
    if _is_exact_discovery(current):
        return True

    copied_marker = bool(getattr(current, _PATCH_ATTR, False))

    @wraps(current)
    def discovery_v355(manager: Any) -> list[tuple[str, Any]]:
        candidates = getattr(_v285(), "_platform_candidates", None)
        if not callable(candidates):
            # Preserve the prior fail-closed discovery contract if v285 is not
            # available for any reason; never synthesize a refresh candidate.
            return current(manager)
        result = candidates(manager)
        return list(result or ())

    discovery_v355.__name__ = "discovery_v355"
    setattr(discovery_v355, _PATCH_ATTR, True)
    setattr(discovery_v355, "__wrapped__", current)
    v108._connected_unsynced_platform_brokers = discovery_v355

    if copied_marker:
        LOGGER.warning(
            "RUNTIME_PLATFORM_STALE_SNAPSHOT_RECOVERY_V355_REASSERTED marker=%s "
            "reason=copied_marker_foreign_owner exact_owner_restored=true "
            "snapshot_ttl_unchanged=true stale_promoted=false safety_gates_bypassed=false",
            MARKER,
        )
    return _is_exact_discovery(getattr(v108, "_connected_unsynced_platform_brokers", None))


def _monitor() -> None:
    """Keep exact v355 discovery outermost after later wrapper churn.

    This monitor changes no readiness or broker state. It only repairs the function
    ownership defect proven by exact module/name identity and then leaves v108's
    existing bounded dispatch/worker behavior untouched.
    """
    while True:
        time.sleep(_MONITOR_INTERVAL_S)
        try:
            with _LOCK:
                current = getattr(_v108(), "_connected_unsynced_platform_brokers", None)
                if not _is_exact_discovery(current):
                    _patch_discovery()
        except Exception as exc:
            LOGGER.warning(
                "RUNTIME_PLATFORM_STALE_SNAPSHOT_RECOVERY_V355_MONITOR_DEFERRED marker=%s "
                "error=%s:%s fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )


def _start_monitor() -> bool:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return True
    try:
        thread = threading.Thread(
            target=_monitor,
            name="runtime-platform-stale-snapshot-recovery-v355-monitor",
            daemon=True,
        )
        thread.start()
        _MONITOR_STARTED = True
        return True
    except Exception:
        return False


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_platform_stale_snapshot_recovery_v355"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        discovery_ok = _patch_discovery()
        monitor_ok = _start_monitor()
        manifest_ok = _register_manifest()
        ready = bool(discovery_ok and monitor_ok and manifest_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if ready:
            LOGGER.critical(
                "RUNTIME_PLATFORM_STALE_SNAPSHOT_RECOVERY_V355_READY marker=%s ready=true "
                "v108_discovery_uses_v285_strong_proof=true adopted_but_stale_refreshable=true "
                "exact_discovery_owner_required=true copied_marker_false_positive_blocked=true "
                "wrapper_churn_monitor=true snapshot_ttl_unchanged=true authoritative_fetch_required=true "
                "single_flight_unchanged=true retry_bounds_unchanged=true stale_promoted=false "
                "position_success_fabricated=false execution_proof_fabricated=false "
                "kill_switch_unchanged=true safety_gates_bypassed=false",
                MARKER,
            )
        else:
            LOGGER.critical(
                "RUNTIME_PLATFORM_STALE_SNAPSHOT_RECOVERY_V355_FAILED marker=%s discovery_ok=%s "
                "monitor_ok=%s manifest_ok=%s fail_closed=true",
                MARKER,
                str(discovery_ok).lower(),
                str(monitor_ok).lower(),
                str(manifest_ok).lower(),
            )
        return ready


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_is_exact_discovery",
    "_patch_discovery",
    "_start_monitor",
]
