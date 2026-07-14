"""Keep Kraken account recovery strictly position-management and exit-only.

``account_exit_management_recovery_patch`` historically called
``TradingStrategy.run_cycle(user_mode=True)`` after adopting positions.  That path
still enters ``NijaCoreLoop.run_scan_phase`` and can collide with the normal
independent Kraken trader, even though recovery explicitly disallows entries.

The account-local Kraken exit runtime already performs private-authenticated,
verified-cost-basis profit/break-even and emergency exit evaluation.  This guard
therefore performs adoption/snapshot refresh and invokes that direct exit scanner
without entering Phase 3.  Non-Kraken recovery behavior is unchanged.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any, Mapping

logger = logging.getLogger("nija.kraken_exit_only_recovery_phase_guard")
_MARKER = "20260714-kraken-exit-only-recovery-v1"
_PATCH_ATTR = "_nija_kraken_exit_only_recovery_phase_guard_v1"
_LOCK = threading.RLock()
_ORIGINAL_IMPORT = None
_PATCHED: set[tuple[str, int]] = set()
_LAST_SYNC: dict[tuple[int, str], float] = {}
_SYNC_LOCK = threading.RLock()


def _is_kraken(broker: Any) -> bool:
    if broker is None:
        return False
    values = (
        type(broker).__name__,
        getattr(broker, "NAME", ""),
        getattr(getattr(broker, "broker_type", None), "value", getattr(broker, "broker_type", "")),
        getattr(broker, "exchange", ""),
    )
    return any("kraken" in str(value or "").lower() for value in values)


def _safe_count(module: ModuleType, name: str, broker: Any) -> int:
    method = getattr(module, name, None)
    if not callable(method):
        return 0
    try:
        return max(0, int(method(broker) or 0))
    except Exception:
        return 0


def _adopt_positions(strategy: Any, identity: str, broker: Any) -> tuple[int, int]:
    positions = 0
    orders = 0
    adopter = getattr(strategy, "adopt_existing_positions", None)
    if callable(adopter):
        try:
            status = adopter(
                broker=broker,
                broker_name=identity,
                account_id=str(identity or "platform:kraken").upper().replace(":", "_"),
            ) or {}
            if isinstance(status, Mapping):
                positions = max(
                    int(status.get("positions_found", 0) or 0),
                    int(status.get("positions_adopted", 0) or 0),
                )
                orders = max(0, int(status.get("open_orders_count", 0) or 0))
        except Exception as exc:
            logger.warning(
                "KRAKEN_EXIT_ONLY_ADOPTION_FAILED marker=%s account=%s error=%s",
                _MARKER,
                identity,
                exc,
            )
    return positions, orders


def _refresh_exact_snapshot(strategy: Any, broker: Any, identity: str) -> None:
    interval = max(5.0, float(os.environ.get("NIJA_KRAKEN_EXIT_ONLY_SYNC_INTERVAL_S", "30") or 30))
    key = (id(broker), str(identity or ""))
    now = time.monotonic()
    with _SYNC_LOCK:
        previous = _LAST_SYNC.get(key, 0.0)
        if now - previous < interval:
            return
        _LAST_SYNC[key] = now
    try:
        try:
            from bot.startup_position_sync import sync_exchange_positions_on_startup
        except ImportError:
            from startup_position_sync import sync_exchange_positions_on_startup  # type: ignore[import]
        sync_exchange_positions_on_startup(strategy)
        logger.info(
            "KRAKEN_EXIT_ONLY_POSITION_SNAPSHOT_REFRESHED marker=%s account=%s",
            _MARKER,
            identity,
        )
    except Exception as exc:
        logger.warning(
            "KRAKEN_EXIT_ONLY_POSITION_SNAPSHOT_REFRESH_FAILED marker=%s account=%s error=%s",
            _MARKER,
            identity,
            exc,
        )


def _scan_exits(trader: Any, identity: str, broker: Any) -> int:
    for name in (
        "bot.kraken_all_account_exit_runtime_patch",
        "kraken_all_account_exit_runtime_patch",
    ):
        try:
            module = importlib.import_module(name)
        except Exception:
            continue
        scanner = getattr(module, "_scan_account_exits", None)
        if callable(scanner):
            return max(0, int(scanner(trader, identity, broker) or 0))
    raise RuntimeError("kraken_all_account_exit_scanner_unavailable")


def _patch_recovery_module(module: ModuleType) -> bool:
    current = getattr(module, "_adopt_and_manage", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    @wraps(current)
    def adopt_and_manage(trader: Any, identity: str, broker: Any):
        if not _is_kraken(broker):
            return current(trader, identity, broker)

        strategy = getattr(trader, "trading_strategy", None)
        positions = _safe_count(module, "_position_count", broker)
        orders = _safe_count(module, "_open_order_count", broker)
        if strategy is not None:
            adopted_positions, adopted_orders = _adopt_positions(strategy, identity, broker)
            positions = max(positions, adopted_positions)
            orders = max(orders, adopted_orders)
            _refresh_exact_snapshot(strategy, broker, identity)

        exits = 0
        try:
            exits = _scan_exits(trader, identity, broker)
        except Exception as exc:
            logger.exception(
                "KRAKEN_EXIT_ONLY_DIRECT_SCAN_FAILED marker=%s account=%s error=%s",
                _MARKER,
                identity,
                exc,
            )

        positions = max(positions, _safe_count(module, "_position_count", broker))
        orders = max(orders, _safe_count(module, "_open_order_count", broker))
        logger.critical(
            "KRAKEN_EXIT_ONLY_RECOVERY_CYCLE marker=%s account=%s positions=%d open_orders=%d exits=%d "
            "entries_allowed=false phase3_skipped=true direct_exit_scanner=true",
            _MARKER,
            identity,
            positions,
            orders,
            exits,
        )
        return positions, orders

    setattr(adopt_and_manage, _PATCH_ATTR, True)
    setattr(adopt_and_manage, "__wrapped__", current)
    module._adopt_and_manage = adopt_and_manage
    os.environ["NIJA_KRAKEN_EXIT_ONLY_RECOVERY_PHASE_GUARD_INSTALLED"] = "1"
    logger.critical(
        "KRAKEN_EXIT_ONLY_RECOVERY_PHASE_GUARD_INSTALLED marker=%s phase3_skipped=true",
        _MARKER,
    )
    return True


def _patch_module(module: ModuleType) -> bool:
    name = str(getattr(module, "__name__", ""))
    key = (name, id(module))
    if key in _PATCHED:
        return True
    if not name.endswith("account_exit_management_recovery_patch"):
        return False
    changed = _patch_recovery_module(module)
    if changed:
        _PATCHED.add(key)
    return changed


def _patch_loaded() -> bool:
    changed = False
    for module in tuple(sys.modules.values()):
        if isinstance(module, ModuleType):
            try:
                changed = _patch_module(module) or changed
            except Exception:
                continue
    for name in (
        "account_exit_management_recovery_patch",
        "bot.account_exit_management_recovery_patch",
    ):
        try:
            module = importlib.import_module(name)
        except Exception:
            continue
        if isinstance(module, ModuleType):
            changed = _patch_module(module) or changed
    return changed


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT
    _patch_loaded()
    with _LOCK:
        if _ORIGINAL_IMPORT is None:
            _ORIGINAL_IMPORT = builtins.__import__
            local = threading.local()

            def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
                module = _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)  # type: ignore[misc]
                if getattr(local, "active", False):
                    return module
                local.active = True
                try:
                    _patch_loaded()
                finally:
                    local.active = False
                return module

            builtins.__import__ = guarded_import  # type: ignore[assignment]
    if not _patch_loaded():
        raise RuntimeError("account_exit_management_recovery_not_patchable")


def install() -> None:
    install_import_hook()


__all__ = [
    "install",
    "install_import_hook",
    "_is_kraken",
    "_patch_recovery_module",
    "_scan_exits",
]
