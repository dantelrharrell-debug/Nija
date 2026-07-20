"""Fail closed on new entries while any held position lacks verified cost basis.

Existing positions remain available to the exit supervisor, but Phase 3 entry scanning is
blocked for the exact broker/account until Kraken private trade history has reconstructed
a trustworthy entry price. This prevents NIJA from adding risk while take-profit geometry
cannot be calculated safely.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any, Iterable, Mapping

logger = logging.getLogger("nija.position_cost_basis_entry_lock")
_MARKER = "20260720-position-cost-basis-entry-lock-v1"
_PATCH_ATTR = "_nija_position_cost_basis_entry_lock_v1"
_LOCK = threading.RLock()
_STARTED = False


def _f(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value or 0.0)
    except Exception:
        return default
    return parsed if parsed == parsed else default


def _broker(core: Any) -> Any:
    for name in ("broker", "_broker", "broker_instance", "execution_broker"):
        value = getattr(core, name, None)
        if value is not None:
            return value
    strategy = getattr(core, "strategy", None) or getattr(core, "trading_strategy", None)
    return getattr(strategy, "broker", None) if strategy is not None else None


def _identity(broker: Any) -> str:
    for name in ("account_id", "_account_id", "user_id", "account_name", "label", "owner_id"):
        value = getattr(broker, name, None)
        if value:
            return str(value).strip().lower().replace(" ", "_")
    return "platform"


def _verified_rows(broker: Any) -> list[Mapping[str, Any]]:
    try:
        from bot import kraken_all_account_exit_runtime_patch as runtime
    except Exception:
        import kraken_all_account_exit_runtime_patch as runtime  # type: ignore
    rows = getattr(runtime, "_position_rows", None)
    if not callable(rows):
        return []
    result: list[Mapping[str, Any]] = []
    for row in rows(broker):
        if isinstance(row, Mapping):
            result.append(row)
    return result


def _unverified(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    unresolved: list[Mapping[str, Any]] = []
    for row in rows:
        qty = _f(row.get("quantity", row.get("qty", row.get("volume", row.get("size", 0.0)))))
        if qty <= 0:
            continue
        entry = max(
            _f(row.get("entry_price")),
            _f(row.get("avg_entry_price")),
            _f(row.get("average_entry_price")),
            _f(row.get("cost_basis")),
        )
        verified = row.get("cost_basis_verified") is True
        blocked = row.get("auto_exit_blocked") is True
        if entry <= 0 or not verified or blocked:
            unresolved.append(row)
    return unresolved


def _patch_class(cls: type) -> bool:
    current = getattr(cls, "_phase3_scan_and_enter", None)
    if not callable(current) or getattr(current, _PATCH_ATTR, False):
        return bool(callable(current) and getattr(current, _PATCH_ATTR, False))

    @wraps(current)
    def guarded(self: Any, *args: Any, **kwargs: Any):
        broker = _broker(self)
        if broker is None:
            logger.critical("POSITION_COST_BASIS_ENTRY_LOCK_FAIL_CLOSED marker=%s reason=broker_missing", _MARKER)
            return []
        try:
            rows = _verified_rows(broker)
            unresolved = _unverified(rows)
        except Exception as exc:
            logger.critical(
                "POSITION_COST_BASIS_ENTRY_LOCK_FAIL_CLOSED marker=%s account=%s reason=verification_error error=%s",
                _MARKER, _identity(broker), exc,
            )
            return []
        if unresolved:
            symbols = ",".join(str(row.get("symbol") or row.get("pair") or "unknown") for row in unresolved[:20])
            logger.critical(
                "POSITION_COST_BASIS_ENTRY_BLOCKED marker=%s account=%s unresolved=%d symbols=%s exits_remain_enabled=true",
                _MARKER, _identity(broker), len(unresolved), symbols,
            )
            setattr(self, "_nija_new_entries_blocked", True)
            setattr(self, "_nija_new_entries_block_reason", "unverified_position_cost_basis")
            return []
        setattr(self, "_nija_new_entries_blocked", False)
        setattr(self, "_nija_new_entries_block_reason", "")
        logger.info(
            "POSITION_COST_BASIS_ENTRY_UNLOCKED marker=%s account=%s verified_positions=%d",
            _MARKER, _identity(broker), len(rows),
        )
        return current(self, *args, **kwargs)

    setattr(guarded, _PATCH_ATTR, True)
    setattr(guarded, "__wrapped__", current)
    setattr(cls, "_phase3_scan_and_enter", guarded)
    logger.critical("POSITION_COST_BASIS_ENTRY_LOCK_PATCHED marker=%s module=%s class=%s", _MARKER, cls.__module__, cls.__name__)
    return True


def _patch_loaded() -> bool:
    changed = False
    for name in ("bot.nija_core_loop", "nija_core_loop"):
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            continue
        cls = getattr(module, "NijaCoreLoop", None)
        if isinstance(cls, type):
            changed = _patch_class(cls) or changed
    return changed


def _watchdog() -> None:
    while True:
        try:
            _patch_loaded()
        except Exception as exc:
            logger.debug("POSITION_COST_BASIS_ENTRY_LOCK_RETRY marker=%s error=%s", _MARKER, exc)
        time.sleep(1.0)


def install() -> bool:
    global _STARTED
    with _LOCK:
        # Cost-basis recovery must be installed before the entry lock evaluates rows.
        from bot import kraken_verified_cost_basis_recovery_patch as recovery
        recovery.install()
        _patch_loaded()
        if not _STARTED:
            _STARTED = True
            threading.Thread(target=_watchdog, name="PositionCostBasisEntryLock", daemon=True).start()
        os.environ["NIJA_POSITION_COST_BASIS_ENTRY_LOCK_INSTALLED"] = "1"
        logger.critical("POSITION_COST_BASIS_ENTRY_LOCK_INSTALLED marker=%s fail_closed=true exits_remain_enabled=true", _MARKER)
        return True


__all__ = ["install", "_unverified", "_patch_class"]
