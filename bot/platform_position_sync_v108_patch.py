"""Dispatch authoritative platform position sync independently of capital readiness.

Production deployment 32c124c showed a circular startup dependency:
CapitalAuthority published a fresh three-broker live snapshot, while canonical
readiness remained false because every platform broker still had
``_startup_position_sync_adopted == False``.  The historical runtime repair only
started reconciliation after ``refresh_capital_authority()`` returned ready with
positive capital, so position sync could wait behind a readiness path that was
itself blocked by position sync.

v108 breaks that liveness cycle without weakening safety:
* connected platform brokers are discovered before each capital refresh;
* each unsynchronized broker gets one daemon reconciliation worker at a time;
* workers call the existing ``startup_position_sync._adopt_broker_positions``
  path, which is already bounded by v95 and fail-closed by v98;
* empty snapshots count only when the broker actually returned an authoritative
  empty result through that existing path;
* canonical v96 position-sync readiness is republished after every attempt;
* no balance, connectivity, capital, position, writer, nonce, strategy,
  bootstrap, risk, kill-switch, or execution readiness is synthesized.

This module deliberately does not add another ``builtins.__import__`` wrapper.
A short-lived monitor patches MABM once it is loaded, then exits.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.platform_position_sync_v108")
MARKER = "20260816-platform-position-sync-v108"
_PATCH_ATTR = "_nija_platform_position_sync_v108"
_LOCK = threading.RLock()
_ACTIVE: set[tuple[int, int]] = set()
_INSTALLED = False
_MONITOR_STARTED = False


def _broker_name(broker_type: Any) -> str:
    return str(getattr(broker_type, "value", broker_type) or "unknown").lower()


def _connected_unsynced_platform_brokers(manager: Any) -> list[tuple[str, Any]]:
    found: list[tuple[str, Any]] = []
    try:
        platform = getattr(manager, "platform_brokers", {}) or {}
        if callable(platform):
            platform = platform()
        for broker_type, broker in dict(platform or {}).items():
            if broker is None or not bool(getattr(broker, "connected", False)):
                continue
            if bool(getattr(broker, "_startup_position_sync_adopted", False)):
                continue
            found.append((_broker_name(broker_type), broker))
    except Exception as exc:
        LOGGER.warning(
            "PLATFORM_POSITION_SYNC_V108_DISCOVERY_FAILED marker=%s error=%s:%s fail_closed=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
    return found


def _publish_readiness(manager: Any, source: str) -> None:
    try:
        try:
            from bot.position_sync_dispatch_authority_v96_patch import publish_position_sync_readiness
        except ImportError:
            from position_sync_dispatch_authority_v96_patch import publish_position_sync_readiness  # type: ignore[import]
        publish_position_sync_readiness(manager, source=source)
    except Exception as exc:
        LOGGER.warning(
            "PLATFORM_POSITION_SYNC_V108_READINESS_PUBLISH_FAILED marker=%s source=%s error=%s:%s fail_closed=true",
            MARKER,
            source,
            type(exc).__name__,
            exc,
        )


def _worker(manager: Any, broker_name: str, broker: Any, key: tuple[int, int], trigger: str) -> None:
    try:
        try:
            from bot import startup_position_sync as sync_module
        except ImportError:
            import startup_position_sync as sync_module  # type: ignore[import]

        get_eps = getattr(sync_module, "_get_entry_price_store", None)
        eps = get_eps() if callable(get_eps) else None
        adopt = getattr(sync_module, "_adopt_broker_positions", None)
        if not callable(adopt):
            raise RuntimeError("startup position-sync adopter unavailable")

        LOGGER.critical(
            "PLATFORM_POSITION_SYNC_V108_START marker=%s broker=%s trigger=%s authoritative_fetch=true synthetic_empty_snapshot=false",
            MARKER,
            broker_name,
            trigger,
        )
        adopt(broker, f"platform:{broker_name}", eps)
        synced = bool(getattr(broker, "_startup_position_sync_adopted", False))
        LOGGER.critical(
            "PLATFORM_POSITION_SYNC_V108_COMPLETE marker=%s broker=%s trigger=%s synced=%s fetch_ok=%s error=%s",
            MARKER,
            broker_name,
            trigger,
            str(synced).lower(),
            getattr(broker, "_startup_position_sync_fetch_ok", None),
            getattr(broker, "_startup_position_sync_error", None),
        )
    except BaseException as exc:
        try:
            setattr(broker, "_startup_position_sync_adopted", False)
            setattr(broker, "_startup_position_sync_fetch_ok", False)
            setattr(broker, "_startup_position_sync_error", f"{type(exc).__name__}:{exc}")
        except Exception:
            pass
        LOGGER.warning(
            "PLATFORM_POSITION_SYNC_V108_FAILED marker=%s broker=%s trigger=%s error=%s:%s trading_fail_closed=true",
            MARKER,
            broker_name,
            trigger,
            type(exc).__name__,
            exc,
        )
    finally:
        _publish_readiness(manager, source=f"v108:{trigger}:{broker_name}")
        with _LOCK:
            _ACTIVE.discard(key)


def dispatch_platform_position_sync(manager: Any, *, trigger: str) -> int:
    """Start at most one authoritative reconciliation worker per platform broker."""
    started = 0
    for broker_name, broker in _connected_unsynced_platform_brokers(manager):
        key = (id(manager), id(broker))
        with _LOCK:
            if key in _ACTIVE:
                continue
            _ACTIVE.add(key)
        try:
            thread = threading.Thread(
                target=_worker,
                args=(manager, broker_name, broker, key, trigger),
                name=f"platform-position-sync-v108-{broker_name}",
                daemon=True,
            )
            thread.start()
            started += 1
        except BaseException:
            with _LOCK:
                _ACTIVE.discard(key)
            raise
    if started:
        LOGGER.info(
            "PLATFORM_POSITION_SYNC_V108_DISPATCH marker=%s trigger=%s workers_started=%d capital_ready_required=false",
            MARKER,
            trigger,
            started,
        )
    return started


def _patch_mabm(module: ModuleType) -> bool:
    cls = getattr(module, "MultiAccountBrokerManager", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "refresh_capital_authority", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def refresh_capital_authority_v108(self: Any, *args: Any, **kwargs: Any):
        trigger = str(kwargs.get("trigger", args[0] if args else "refresh_capital_authority"))
        try:
            dispatch_platform_position_sync(self, trigger=trigger)
        except Exception as exc:
            LOGGER.warning(
                "PLATFORM_POSITION_SYNC_V108_DISPATCH_FAILED marker=%s trigger=%s error=%s:%s capital_refresh_continues=true trading_fail_closed=true",
                MARKER,
                trigger,
                type(exc).__name__,
                exc,
            )
        return current(self, *args, **kwargs)

    setattr(refresh_capital_authority_v108, _PATCH_ATTR, True)
    setattr(refresh_capital_authority_v108, "__wrapped__", current)
    cls.refresh_capital_authority = refresh_capital_authority_v108  # type: ignore[assignment]
    LOGGER.critical(
        "PLATFORM_POSITION_SYNC_V108_MABM_PATCHED marker=%s module=%s dispatch_before_capital_refresh=true capital_ready_dependency=false safety_gates_unchanged=true",
        MARKER,
        module.__name__,
    )
    return True


def _patch_loaded() -> bool:
    patched = False
    seen: set[int] = set()
    for name in ("bot.multi_account_broker_manager", "multi_account_broker_manager"):
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType) or id(module) in seen:
            continue
        seen.add(id(module))
        patched = _patch_mabm(module) or patched
    return patched


def _patch_monitor() -> None:
    deadline = time.monotonic() + 90.0
    while time.monotonic() < deadline:
        try:
            if _patch_loaded():
                return
        except Exception:
            pass
        time.sleep(0.05)
    LOGGER.critical(
        "PLATFORM_POSITION_SYNC_V108_PATCH_TIMEOUT marker=%s mabm_unavailable=true trading_fail_closed=true",
        MARKER,
    )


def install() -> bool:
    global _INSTALLED, _MONITOR_STARTED
    with _LOCK:
        if _INSTALLED:
            _patch_loaded()
            return True
        patched = _patch_loaded()
        if not patched and not _MONITOR_STARTED:
            _MONITOR_STARTED = True
            threading.Thread(
                target=_patch_monitor,
                name="platform-position-sync-v108-patch-monitor",
                daemon=True,
            ).start()
        os.environ["NIJA_PLATFORM_POSITION_SYNC_V108_INSTALLED"] = "1"
        _INSTALLED = True
        LOGGER.critical(
            "PLATFORM_POSITION_SYNC_V108_INSTALLED marker=%s direct_platform_dispatch=true capital_ready_dependency=false single_flight=true import_hook=false synthetic_empty_snapshot=false",
            MARKER,
        )
        return True


def install_import_hook() -> bool:
    # Compatibility with the canonical installer naming convention. No import
    # hook is installed; install() uses direct patching plus a bounded monitor.
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "dispatch_platform_position_sync",
    "_connected_unsynced_platform_brokers",
    "_patch_mabm",
]
