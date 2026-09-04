"""Recover stale platform position snapshots through v108 without weakening v285 truth.

Production 2026-09-04 showed platform:kraken remaining stale for >240s while
v285 repeatedly requested recovery with ``platform_refresh_workers=0``.  v285
correctly treats an adopted-but-stale authoritative snapshot as not ready, but
its recovery path calls ``v108.dispatch_platform_position_sync``.  v108's
legacy discovery only checks ``_startup_position_sync_adopted`` and therefore
skips a broker whose adoption latch is still true even when the v285 snapshot
has expired.

v355 makes v108 discovery use v285's stronger platform candidate predicate.
This starts a bounded existing v108 reconciliation worker for stale/missing
current authoritative snapshots while preserving the existing 90s freshness
TTL, authoritative fetch requirement, v98 adoption path, single-flight worker,
retry bounds, and all execution safety gates.

No position/capital/readiness/fill is fabricated.  No TTL is extended, no stale
snapshot is promoted, no order is forced, and no kill switch or rejection latch
is changed.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_platform_stale_snapshot_recovery_v355")
MARKER = "20260904-runtime-platform-stale-snapshot-recovery-v355"
RELEASE_ID = "20260904-runtime-convergence-v355"
_READY_FLAG = "NIJA_RUNTIME_PLATFORM_STALE_SNAPSHOT_RECOVERY_V355_READY"
_PATCH_ATTR = "_nija_runtime_platform_stale_snapshot_recovery_v355"
_LOCK = threading.RLock()


def _v108() -> Any:
    return importlib.import_module("bot.platform_position_sync_v108_patch")


def _v285() -> Any:
    return importlib.import_module("bot.runtime_authoritative_position_coverage_v285_patch")


def _patch_discovery() -> bool:
    v108 = _v108()
    current = getattr(v108, "_connected_unsynced_platform_brokers", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

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
    return True


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
        manifest_ok = _register_manifest()
        ready = bool(discovery_ok and manifest_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if ready:
            LOGGER.critical(
                "RUNTIME_PLATFORM_STALE_SNAPSHOT_RECOVERY_V355_READY marker=%s ready=true "
                "v108_discovery_uses_v285_strong_proof=true adopted_but_stale_refreshable=true "
                "snapshot_ttl_unchanged=true authoritative_fetch_required=true "
                "single_flight_unchanged=true retry_bounds_unchanged=true stale_promoted=false "
                "position_success_fabricated=false execution_proof_fabricated=false "
                "kill_switch_unchanged=true safety_gates_bypassed=false",
                MARKER,
            )
        else:
            LOGGER.critical(
                "RUNTIME_PLATFORM_STALE_SNAPSHOT_RECOVERY_V355_FAILED marker=%s discovery_ok=%s manifest_ok=%s fail_closed=true",
                MARKER,
                str(discovery_ok).lower(),
                str(manifest_ok).lower(),
            )
        return ready


def install_import_hook() -> bool:
    return install()


__all__ = ["MARKER", "RELEASE_ID", "install", "install_import_hook", "_patch_discovery"]
