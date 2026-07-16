"""Prevent broker snapshot adoption from corrupting position cost basis.

Broker snapshots are authoritative point-in-time state. They must replace local
quantity and preserve verified cost basis; they must never be processed as new
additive fills. This patch protects every platform and user broker path that
calls ``PositionTracker.track_entry(..., position_source='broker_existing')``.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

logger = logging.getLogger("nija.position_adoption_exit_integrity")
_MARKER = "20260716-position-adoption-exit-integrity-v1"
_PATCHED = False
_MONITOR_STARTED = False
_LOCK = threading.Lock()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value or 0.0)
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed if parsed == parsed else default


def _patch_position_tracker() -> bool:
    try:
        try:
            from bot.position_tracker import PositionTracker
        except ImportError:
            from position_tracker import PositionTracker  # type: ignore[import]
    except Exception:
        return False

    current = getattr(PositionTracker, "track_entry", None)
    if not callable(current):
        return False
    if getattr(current, "_nija_exact_snapshot_guard", False):
        return True

    original = current

    def guarded_track_entry(
        self,
        symbol: str,
        entry_price: float,
        quantity: float,
        size_usd: float,
        strategy: str = "APEX_v7.1",
        position_source: str = "nija_strategy",
    ) -> bool:
        source = str(position_source or "").strip().lower()
        strategy_name = str(strategy or "").strip().upper()
        snapshot_source = source in {
            "broker_existing",
            "broker_sync",
            "startup_sync",
            "position_adoption",
        } or strategy_name in {"STARTUP_SYNC", "BROKER_SYNC", "POSITION_ADOPTION"}

        if not snapshot_source:
            return bool(
                original(
                    self,
                    symbol=symbol,
                    entry_price=entry_price,
                    quantity=quantity,
                    size_usd=size_usd,
                    strategy=strategy,
                    position_source=position_source,
                )
            )

        exact_sync = getattr(self, "sync_position_snapshot", None)
        if not callable(exact_sync):
            logger.critical(
                "POSITION_ADOPTION_EXACT_SYNC_UNAVAILABLE marker=%s symbol=%s action=fail_closed",
                _MARKER,
                symbol,
            )
            return False

        existing = self.get_position(symbol) if callable(getattr(self, "get_position", None)) else None
        supplied_entry = _safe_float(entry_price)
        entry_source = "api" if supplied_entry > 0 else "override"
        ok = bool(
            exact_sync(
                symbol=symbol,
                quantity=_safe_float(quantity),
                entry_price=supplied_entry,
                current_price=0.0,
                size_usd=_safe_float(size_usd),
                strategy="BROKER_SYNC",
                position_source="broker_existing",
                entry_price_source=entry_source,
            )
        )
        final = self.get_position(symbol) if callable(getattr(self, "get_position", None)) else None
        final_qty = _safe_float((final or {}).get("quantity"))
        expected_qty = _safe_float(quantity)
        qty_ok = expected_qty > 0 and abs(final_qty - expected_qty) <= max(1e-10, expected_qty * 1e-8)
        if not ok or not qty_ok:
            logger.critical(
                "POSITION_ADOPTION_EXACT_SYNC_FAILED marker=%s symbol=%s expected_qty=%.8f final_qty=%.8f action=fail_closed",
                _MARKER,
                symbol,
                expected_qty,
                final_qty,
            )
            return False

        old_qty = _safe_float((existing or {}).get("quantity"))
        old_entry = _safe_float((existing or {}).get("entry_price"))
        final_entry = _safe_float((final or {}).get("entry_price"))
        logger.critical(
            "POSITION_ADOPTION_EXACT_SNAPSHOT_APPLIED marker=%s symbol=%s old_qty=%.8f new_qty=%.8f old_entry=%.8f new_entry=%.8f verified=%s auto_exit_blocked=%s",
            _MARKER,
            symbol,
            old_qty,
            final_qty,
            old_entry,
            final_entry,
            (final or {}).get("cost_basis_verified") is True,
            (final or {}).get("auto_exit_blocked") is True,
        )
        return True

    guarded_track_entry._nija_exact_snapshot_guard = True  # type: ignore[attr-defined]
    guarded_track_entry._nija_original = original  # type: ignore[attr-defined]
    PositionTracker.track_entry = guarded_track_entry
    logger.critical("POSITION_ADOPTION_EXACT_SNAPSHOT_GUARD_PATCHED marker=%s", _MARKER)
    return True


def _patch_trading_strategy_verification() -> bool:
    try:
        try:
            from bot.trading_strategy import TradingStrategy
        except ImportError:
            from trading_strategy import TradingStrategy  # type: ignore[import]
    except Exception:
        return False

    current = getattr(TradingStrategy, "verify_position_adoption_status", None)
    if not callable(current):
        return False
    if getattr(current, "_nija_integrity_guard", False):
        return True

    def verify(self, broker: Any, broker_name: str = "", account_id: str = "") -> bool:
        if broker is None:
            return False
        getter = getattr(broker, "get_positions", None)
        tracker = getattr(broker, "position_tracker", None)
        if not callable(getter) or tracker is None:
            return False
        try:
            positions = getter() or []
            iterable = list(positions.values()) if isinstance(positions, dict) else list(positions)
            for position in iterable:
                symbol = self._position_symbol(position)
                quantity = self._position_quantity(position)
                if not symbol or quantity <= 0:
                    continue
                local = tracker.get_position(symbol) if callable(getattr(tracker, "get_position", None)) else None
                local_qty = _safe_float((local or {}).get("quantity"))
                if abs(local_qty - quantity) > max(1e-10, quantity * 1e-8):
                    logger.critical(
                        "POSITION_ADOPTION_VERIFICATION_FAILED marker=%s account=%s broker=%s symbol=%s broker_qty=%.8f local_qty=%.8f",
                        _MARKER,
                        account_id,
                        broker_name,
                        symbol,
                        quantity,
                        local_qty,
                    )
                    return False
            return True
        except Exception as exc:
            logger.warning(
                "POSITION_ADOPTION_VERIFICATION_EXCEPTION marker=%s account=%s broker=%s error=%s",
                _MARKER,
                account_id,
                broker_name,
                exc,
            )
            return False

    verify._nija_integrity_guard = True  # type: ignore[attr-defined]
    TradingStrategy.verify_position_adoption_status = verify
    logger.critical("POSITION_ADOPTION_VERIFICATION_GUARD_PATCHED marker=%s", _MARKER)
    return True


def _apply() -> bool:
    tracker_ready = _patch_position_tracker()
    strategy_ready = _patch_trading_strategy_verification()
    return tracker_ready and strategy_ready


def _monitor() -> None:
    while True:
        try:
            if _apply():
                logger.critical("POSITION_ADOPTION_EXIT_INTEGRITY_READY marker=%s", _MARKER)
                return
        except Exception as exc:
            logger.warning("POSITION_ADOPTION_EXIT_INTEGRITY_RETRY marker=%s error=%s", _MARKER, exc)
        time.sleep(0.5)


def install_import_hook() -> None:
    global _PATCHED, _MONITOR_STARTED
    with _LOCK:
        if _PATCHED and _MONITOR_STARTED:
            return
        _PATCHED = _apply()
        if not _MONITOR_STARTED:
            thread = threading.Thread(
                target=_monitor,
                name="PositionAdoptionExitIntegrity",
                daemon=True,
            )
            thread.start()
            _MONITOR_STARTED = True
    logger.critical(
        "POSITION_ADOPTION_EXIT_INTEGRITY_INSTALLED marker=%s immediate_ready=%s",
        _MARKER,
        _PATCHED,
    )


def install() -> None:
    install_import_hook()
