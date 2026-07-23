"""Prevent partial-fill ledger closes and duplicate exit retries.

This final v25 guard is intentionally narrow. It wraps the broker and engine
fill-confirmation modules so a position is closed only after the full requested
quantity is confirmed filled. Orders whose status remains unknown stay pending
and are never resubmitted as a second sell until the original order reaches a
terminal failure or full-fill state.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from bot import auto_exit_sl_tp_runtime_patch as auto_exit
from bot import live_broker_profit_exit_convergence_v25 as broker_v25
from bot import live_engine_profit_exit_convergence_v25 as engine_v25
from bot import universal_broker_exit_supervisor_patch as supervisor

logger = logging.getLogger("nija.live_exit_reconciliation_safety")
_MARKER = "20260723-live-exit-reconciliation-safety-v25"
_INSTALLED = False
_ORIGINAL_BROKER_SCAN = broker_v25._scan_broker


def _full_fill_confirmed(payload: Any, expected_quantity: float) -> bool:
    if not isinstance(payload, dict):
        return False
    state = broker_v25._status(payload)
    if state in {"filled", "closed", "done", "complete", "completed", "settled"}:
        return True
    if broker_v25._is_terminal_failure(payload):
        return False
    filled = broker_v25._filled_quantity(payload)
    expected = max(0.0, float(expected_quantity or 0.0))
    if expected <= 0:
        return False
    tolerance = max(1e-12, expected * 1e-8)
    return filled + tolerance >= expected


def _broker_confirm_and_close(
    pending: broker_v25.PendingExit,
    payload: dict[str, Any],
) -> bool:
    broker = pending.broker
    pos = pending.position
    expected = auto_exit._quantity(pos)
    if not _full_fill_confirmed(payload, expected):
        filled = broker_v25._filled_quantity(payload)
        if filled > 0:
            logger.warning(
                "LIVE_BROKER_EXIT_PARTIAL_FILL_PENDING marker=%s venue=%s account=%s symbol=%s order_id=%s filled=%.12f expected=%.12f position_remains_open=true",
                _MARKER,
                auto_exit._broker_label(broker),
                supervisor._account_label(broker),
                auto_exit._sym(pos.get("symbol")),
                broker_v25._order_id(payload) or broker_v25._order_id(pending.order),
                filled,
                expected,
            )
        return False
    merged = dict(pending.order)
    merged.update(payload)
    supervisor._mark_closed(broker, pos, merged, pending.reason, pending.market)
    auto_exit._HIGH_WATER.pop(auto_exit._position_key(pos), None)
    logger.critical(
        "LIVE_BROKER_EXIT_FULL_FILL_CONFIRMED marker=%s venue=%s account=%s symbol=%s reason=%s order_id=%s filled=%.12f expected=%.12f",
        _MARKER,
        auto_exit._broker_label(broker),
        supervisor._account_label(broker),
        auto_exit._sym(pos.get("symbol")),
        pending.reason,
        broker_v25._order_id(merged),
        broker_v25._filled_quantity(merged),
        expected,
    )
    return True


def _engine_mark_closed(
    engine: Any,
    pending: broker_v25.PendingExit,
    payload: dict[str, Any],
) -> bool:
    expected = auto_exit._quantity(pending.position)
    if not _full_fill_confirmed(payload, expected):
        filled = broker_v25._filled_quantity(payload)
        if filled > 0:
            logger.warning(
                "LIVE_ENGINE_EXIT_PARTIAL_FILL_PENDING marker=%s symbol=%s order_id=%s filled=%.12f expected=%.12f position_remains_open=true",
                _MARKER,
                auto_exit._sym(pending.position.get("symbol")),
                broker_v25._order_id(payload) or broker_v25._order_id(pending.order),
                filled,
                expected,
            )
        return False

    pos = pending.position
    symbol = auto_exit._sym(pos.get("symbol"))
    pid = str(pos.get("position_id") or symbol)
    merged = dict(pending.order)
    merged.update(payload)
    fill = broker_v25._f(
        auto_exit._get(
            merged,
            "filled_price",
            "average_fill_price",
            "avg_price",
            "price",
            default=pending.market,
        ),
        pending.market,
    )
    fee = broker_v25._f(
        auto_exit._get(merged, "fee", "commission", "fees", default=0.0)
    )
    oid = broker_v25._order_id(merged)
    close_fn = getattr(engine, "close_position_with_pnl", None)
    ledger = getattr(engine, "trade_ledger", None)
    if callable(close_fn):
        result = close_fn(
            position_id=pid,
            symbol=symbol,
            exit_price=fill,
            exit_fee=fee,
            exit_reason=pending.reason,
            order_id=oid,
            broker=auto_exit._broker_label(pending.broker),
        )
    elif ledger is not None and callable(getattr(ledger, "close_position_with_pnl", None)):
        result = ledger.close_position_with_pnl(
            position_id=pid,
            symbol=symbol,
            exit_price=fill,
            exit_fee=fee,
            exit_reason=pending.reason,
            order_id=oid,
            broker=auto_exit._broker_label(pending.broker),
        )
    else:
        return False
    if isinstance(result, dict) and result.get("success") is False:
        return False
    auto_exit._HIGH_WATER.pop(auto_exit._position_key(pos), None)
    logger.critical(
        "LIVE_ENGINE_EXIT_FULL_FILL_CONFIRMED marker=%s symbol=%s position_id=%s reason=%s order_id=%s filled=%.12f expected=%.12f",
        _MARKER,
        symbol,
        pid,
        pending.reason,
        oid,
        broker_v25._filled_quantity(merged),
        expected,
    )
    return True


def _safe_broker_scan(broker: Any) -> int:
    now = time.monotonic()
    extension = 30.0
    for pending in tuple(broker_v25._PENDING.values()):
        if pending.broker is broker and pending.deadline <= now:
            pending.deadline = now + extension
            logger.error(
                "LIVE_BROKER_EXIT_UNKNOWN_ORDER_QUARANTINED marker=%s venue=%s account=%s symbol=%s order_id=%s duplicate_exit_blocked=true next_reconcile_s=%.1f",
                _MARKER,
                auto_exit._broker_label(broker),
                supervisor._account_label(broker),
                auto_exit._sym(pending.position.get("symbol")),
                broker_v25._order_id(pending.order),
                extension,
            )
    return _ORIGINAL_BROKER_SCAN(broker)


def install_import_hook() -> bool:
    global _INSTALLED
    broker_v25._confirm_and_close = _broker_confirm_and_close
    broker_v25._scan_broker = _safe_broker_scan
    supervisor._scan_broker = _safe_broker_scan
    engine_v25._mark_engine_closed = _engine_mark_closed
    if _INSTALLED:
        return True
    _INSTALLED = True
    logger.critical(
        "LIVE_EXIT_RECONCILIATION_SAFETY_V25_INSTALLED marker=%s full_fill_required=true partial_fill_stays_open=true duplicate_exit_retry_blocked=true",
        _MARKER,
    )
    return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "install",
    "install_import_hook",
    "_full_fill_confirmed",
    "_broker_confirm_and_close",
    "_engine_mark_closed",
    "_safe_broker_scan",
]
