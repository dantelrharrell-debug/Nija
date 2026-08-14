"""Production freshness and scan-owner convergence hardening v93.

Production evidence on 2026-08-14 exposed two independent liveness gaps while
all execution safety gates correctly remained fail closed:

1. Capital refresh is triggered by a 10s watchdog after a 30s stale threshold,
   but v78 allowed the synchronous balance batch to wait up to 60s. A refresh
   that begins near 40s of snapshot age can therefore finish after the canonical
   90s freshness TTL. The older preactivation v16 observer can also be loaded
   through ``importlib.import_module`` after v64 installs, bypassing v64's
   builtins-only import hook and reintroducing the legacy 60s freshness view.
2. Duplicate account scans can wait 300s for an existing scan owner. A live but
   slow Coinbase owner was observed at >780s age, tying up a second caller for
   the full five minutes. Blindly replacing a state owned by a live thread would
   be unsafe because it could create concurrent scans for the same account.

v93 closes those gaps without authorizing execution. It bounds the synchronous
capital publication budget against watchdog timing, bridges v64 across
``importlib.import_module``, makes snapshot-publication expiry observable, caps
duplicate scan-result waits, and reclaims scan state only when the recorded
owner thread is actually gone. A live stalled owner is never force-unlocked or
replaced.
"""
from __future__ import annotations

import builtins
from datetime import datetime, timezone
from functools import wraps
import importlib
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.production_freshness_scan_convergence_v93")
MARKER = "20260814-production-freshness-scan-convergence-v93"
_LOCK = threading.RLock()
_INSTALLED = False
_MONITOR_STARTED = False
_LAST_STALL_WARNING: dict[str, float] = {}
_IMPORTLIB_HOOK_FLAG = "_NIJA_PRODUCTION_FRESHNESS_SCAN_V93_IMPORTLIB_HOOK"
_BUILTINS_HOOK_FLAG = "_NIJA_PRODUCTION_FRESHNESS_SCAN_V93_BUILTINS_HOOK"
_V78_ATTR = "_nija_production_freshness_scan_v93"
_CA_ATTR = "_nija_production_freshness_scan_v93"


def _float_env(name: str, default: float, *, minimum: float = 0.0) -> float:
    try:
        value = float(os.environ.get(name, str(default)) or default)
    except (TypeError, ValueError):
        value = float(default)
    return max(float(minimum), value)


def _freshness_ttl_s() -> float:
    return _float_env("NIJA_CAPITAL_FRESHNESS_TTL_S", 90.0, minimum=10.0)


def _watchdog_interval_s() -> float:
    return _float_env("NIJA_CAPITAL_WATCHDOG_INTERVAL_S", 10.0, minimum=1.0)


def _stale_trigger_s() -> float:
    return _float_env("NIJA_CAPITAL_STALE_TIMEOUT_S", 30.0, minimum=1.0)


def _publish_headroom_s() -> float:
    return _float_env("NIJA_CAPITAL_REFRESH_FINALIZE_HEADROOM_S", 5.0, minimum=2.0)


def continuity_budget_ceiling_s() -> float:
    """Latest safe synchronous fetch budget for the watchdog-driven refresh.

    Worst-case refresh start is one watchdog interval after the stale trigger.
    Reserve a small finalization headroom for snapshot construction/publication.
    The result is fail-closed and never extends v78's existing budget.
    """
    ttl = _freshness_ttl_s()
    worst_start_age = _stale_trigger_s() + _watchdog_interval_s()
    return max(5.0, ttl - worst_start_age - _publish_headroom_s())


def _bound_runtime_cadence_env() -> dict[str, float]:
    """Prevent operator cadence values from making freshness mathematically impossible."""
    ttl = _freshness_ttl_s()
    stale = min(_stale_trigger_s(), max(10.0, ttl / 3.0))
    watchdog = min(_watchdog_interval_s(), max(2.0, ttl / 9.0))
    os.environ["NIJA_CAPITAL_STALE_TIMEOUT_S"] = f"{stale:.6f}"
    os.environ["NIJA_CAPITAL_WATCHDOG_INTERVAL_S"] = f"{watchdog:.6f}"

    duplicate_wait = _float_env("NIJA_DUPLICATE_SCAN_RESULT_WAIT_S", 15.0, minimum=5.0)
    duplicate_wait = min(duplicate_wait, 15.0)
    os.environ["NIJA_DUPLICATE_SCAN_RESULT_WAIT_S"] = f"{duplicate_wait:.6f}"
    return {
        "ttl_s": ttl,
        "stale_trigger_s": stale,
        "watchdog_interval_s": watchdog,
        "duplicate_scan_wait_s": duplicate_wait,
    }


def _patch_v78(module: ModuleType) -> bool:
    current = getattr(module, "fetch_budget_seconds", None)
    if not callable(current):
        return False
    if getattr(current, _V78_ATTR, False):
        return True

    @wraps(current)
    def fetch_budget_seconds_v93() -> float:
        base_budget = max(5.0, float(current()))
        ceiling = continuity_budget_ceiling_s()
        return max(5.0, min(base_budget, ceiling))

    setattr(fetch_budget_seconds_v93, _V78_ATTR, True)
    setattr(fetch_budget_seconds_v93, "__wrapped__", current)
    module.fetch_budget_seconds = fetch_budget_seconds_v93
    LOGGER.critical(
        "CAPITAL_REFRESH_V93_BUDGET_PATCHED marker=%s effective_budget_s=%.1f "
        "continuity_ceiling_s=%.1f ttl_s=%.1f stale_trigger_s=%.1f watchdog_s=%.1f",
        MARKER,
        fetch_budget_seconds_v93(),
        continuity_budget_ceiling_s(),
        _freshness_ttl_s(),
        _stale_trigger_s(),
        _watchdog_interval_s(),
    )
    return True


def _patch_v64_bridge(module: ModuleType) -> bool:
    """Apply v64 to already-loaded targets; future importlib loads use our bridge."""
    patch_loaded = getattr(module, "_patch_loaded", None)
    if not callable(patch_loaded):
        return False
    patch_loaded()
    return True


def _normalize_expiry(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _patch_capital_authority(module: ModuleType) -> bool:
    """Make publication status report expiry dynamically instead of latched-false forever."""
    cls = getattr(module, "CapitalAuthority", None)
    status_cls = getattr(module, "SnapshotPublicationStatus", None)
    if not isinstance(cls, type) or status_cls is None:
        return False
    current = getattr(cls, "get_snapshot_publication_status", None)
    if not callable(current):
        return False
    if getattr(current, _CA_ATTR, False):
        return True

    @wraps(current)
    def get_snapshot_publication_status_v93(self: Any):
        status = current(self)
        if bool(getattr(status, "stale", False)):
            return status
        expiry = _normalize_expiry(getattr(status, "expiry", None))
        if expiry is None or datetime.now(timezone.utc) < expiry:
            return status
        try:
            return status_cls(
                accepted=bool(getattr(status, "accepted", False)),
                stale=True,
                reason="snapshot_expired",
                timestamp=getattr(status, "timestamp", None),
                expiry=getattr(status, "expiry", None),
            )
        except Exception:
            return status

    setattr(get_snapshot_publication_status_v93, _CA_ATTR, True)
    setattr(get_snapshot_publication_status_v93, "__wrapped__", current)
    cls.get_snapshot_publication_status = get_snapshot_publication_status_v93
    LOGGER.critical(
        "CAPITAL_PUBLICATION_STATUS_V93_PATCHED marker=%s dynamic_expiry=true",
        MARKER,
    )
    return True


def _thread_ident_alive(ident: Any) -> bool:
    try:
        target = int(ident)
    except (TypeError, ValueError):
        return False
    if target <= 0:
        return False
    return any(
        bool(thread.is_alive()) and thread.ident == target
        for thread in threading.enumerate()
    )


def _scan_module() -> ModuleType | None:
    for name in ("scan_wrapper_convergence_repair_patch", "nija.scan_wrapper_convergence_repair_patch"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            return module
    return None


def _sweep_scan_states_once(module: ModuleType | None = None) -> dict[str, int]:
    """Reclaim only orphaned scan ownership; never replace a live owner's state."""
    module = module or _scan_module()
    result = {"live_stalled": 0, "orphan_reset": 0}
    if module is None:
        return result
    states = getattr(module, "_SCAN_STATES", None)
    guard = getattr(module, "_SCAN_STATES_GUARD", None)
    state_cls = getattr(module, "ScanState", None)
    if not isinstance(states, dict) or guard is None or not isinstance(state_cls, type):
        return result

    min_orphan_age = _float_env("NIJA_SCAN_ORPHAN_RESET_MIN_AGE_S", 60.0, minimum=30.0)
    stall_warn_age = _float_env("NIJA_SCAN_LIVE_OWNER_WARN_AGE_S", 180.0, minimum=60.0)
    now = time.monotonic()
    with guard:
        for key, state in list(states.items()):
            owner = getattr(state, "owner_thread_id", None)
            started = float(getattr(state, "started_at", 0.0) or 0.0)
            if owner is None or started <= 0.0:
                continue
            age = max(0.0, now - started)
            alive = _thread_ident_alive(owner)
            if not alive and age >= min_orphan_age:
                # Re-check identity while holding the canonical state-map guard;
                # replace only the exact state object we inspected.
                if states.get(key) is state and getattr(state, "owner_thread_id", None) == owner:
                    states[key] = state_cls()
                    result["orphan_reset"] += 1
                    LOGGER.critical(
                        "SCAN_ORPHAN_OWNER_RESET marker=%s identity=%s owner_thread=%s "
                        "age_s=%.2f concurrent_scan_created=false next_cycle_retry=true",
                        MARKER,
                        key,
                        owner,
                        age,
                    )
                continue
            if alive and age >= stall_warn_age:
                result["live_stalled"] += 1
                last = float(_LAST_STALL_WARNING.get(str(key), 0.0) or 0.0)
                if (now - last) >= 60.0:
                    _LAST_STALL_WARNING[str(key)] = now
                    LOGGER.critical(
                        "SCAN_LIVE_OWNER_STALLED marker=%s identity=%s owner_thread=%s "
                        "age_s=%.2f action=preserve_owner fail_closed=true",
                        MARKER,
                        key,
                        owner,
                        age,
                    )
    return result


def _scan_owner_monitor() -> None:
    while True:
        try:
            _sweep_scan_states_once()
        except Exception as exc:
            LOGGER.debug("SCAN_OWNER_V93_MONITOR_ERROR error=%s:%s", type(exc).__name__, exc)
        time.sleep(5.0)


def _patch_loaded() -> bool:
    changed = False
    for name in ("bot.capital_refresh_live_continuity_v78_patch", "capital_refresh_live_continuity_v78_patch"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            changed = _patch_v78(module) or changed
    for name in ("bot.live_capital_freshness_v64_patch", "live_capital_freshness_v64_patch"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            changed = _patch_v64_bridge(module) or changed
    for name in ("bot.capital_authority", "capital_authority"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            changed = _patch_capital_authority(module) or changed
    return changed


def _install_import_hooks() -> None:
    if not getattr(importlib.import_module, _IMPORTLIB_HOOK_FLAG, False):
        original_import_module = importlib.import_module

        @wraps(original_import_module)
        def import_module_v93(name: str, package: str | None = None):
            result = original_import_module(name, package)
            text = str(name or "")
            if any(token in text for token in (
                "preactivation_readiness_convergence_v16_patch",
                "live_capital_freshness_v64_patch",
                "capital_refresh_live_continuity_v78_patch",
                "capital_authority",
            )):
                _patch_loaded()
                v64 = sys.modules.get("bot.live_capital_freshness_v64_patch") or sys.modules.get("live_capital_freshness_v64_patch")
                if isinstance(v64, ModuleType):
                    patch_loaded = getattr(v64, "_patch_loaded", None)
                    if callable(patch_loaded):
                        patch_loaded()
            return result

        setattr(import_module_v93, _IMPORTLIB_HOOK_FLAG, True)
        setattr(import_module_v93, "__wrapped__", original_import_module)
        importlib.import_module = import_module_v93

    if not getattr(builtins, _BUILTINS_HOOK_FLAG, False):
        original_import = builtins.__import__

        @wraps(original_import)
        def importing_v93(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
            result = original_import(name, globals, locals, fromlist, level)
            if any(token in str(name or "") for token in (
                "preactivation_readiness_convergence_v16_patch",
                "capital_authority",
            )):
                _patch_loaded()
            return result

        builtins.__import__ = importing_v93
        setattr(builtins, _BUILTINS_HOOK_FLAG, True)


def install_import_hook() -> bool:
    global _INSTALLED, _MONITOR_STARTED
    with _LOCK:
        cadence = _bound_runtime_cadence_env()
        _patch_loaded()
        _install_import_hooks()
        _patch_loaded()
        if not _MONITOR_STARTED:
            _MONITOR_STARTED = True
            threading.Thread(
                target=_scan_owner_monitor,
                name="ProductionFreshnessScanV93",
                daemon=True,
            ).start()
        _INSTALLED = True
        os.environ["NIJA_PRODUCTION_FRESHNESS_SCAN_V93_INSTALLED"] = "1"
        os.environ["NIJA_PRODUCTION_FRESHNESS_SCAN_V93_READY"] = "1"
        LOGGER.critical(
            "PRODUCTION_FRESHNESS_SCAN_V93_INSTALLED marker=%s ttl_s=%.1f "
            "stale_trigger_s=%.1f watchdog_s=%.1f fetch_budget_ceiling_s=%.1f "
            "duplicate_scan_wait_s=%.1f live_scan_owner_force_reset=false",
            MARKER,
            cadence["ttl_s"],
            cadence["stale_trigger_s"],
            cadence["watchdog_interval_s"],
            continuity_budget_ceiling_s(),
            cadence["duplicate_scan_wait_s"],
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "continuity_budget_ceiling_s",
    "install",
    "install_import_hook",
    "_bound_runtime_cadence_env",
    "_patch_capital_authority",
    "_patch_v64_bridge",
    "_patch_v78",
    "_sweep_scan_states_once",
    "_thread_ident_alive",
]
