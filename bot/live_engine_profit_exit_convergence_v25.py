"""Converge ExecutionEngine exits onto fill-confirmed v25 semantics.

The broker-native supervisor is the primary held-position exit path. This module
hardens the parallel ExecutionEngine monitor so an exchange acknowledgement can
never be recorded as a completed close before a real fill is observed. It also
wraps the existing auto-exit class patcher, ensuring ExecutionEngine classes
imported later receive the same v25 scanner.
"""
from __future__ import annotations

import logging
import os
import sys
import time
from typing import Any

from bot import auto_exit_sl_tp_runtime_patch as auto_exit
from bot import live_broker_profit_exit_convergence_v25 as broker_v25

logger = logging.getLogger("nija.live_engine_profit_exit_convergence")
_MARKER = "20260723-live-engine-profit-exit-v25"
_INSTALLED = False
_PENDING: dict[str, broker_v25.PendingExit] = {}
_ORIGINAL_PATCH_ENGINE = auto_exit._patch_engine
_PATCHED_CLASS_ATTR = "__nija_live_engine_profit_exit_v25__"


def _key(engine: Any, pos: dict[str, Any]) -> str:
    symbol = auto_exit._sym(pos.get("symbol"))
    pid = str(pos.get("position_id") or symbol)
    return f"{id(engine)}:{pid}:{symbol}"


def _mark_engine_closed(
    engine: Any,
    pending: broker_v25.PendingExit,
    payload: dict[str, Any],
) -> bool:
    if not broker_v25._is_filled(payload):
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
    fee = broker_v25._f(auto_exit._get(merged, "fee", "commission", "fees", default=0.0))
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
        logger.error(
            "LIVE_ENGINE_EXIT_CLOSE_RECORDER_MISSING marker=%s symbol=%s position_id=%s",
            _MARKER,
            symbol,
            pid,
        )
        return False
    if isinstance(result, dict) and result.get("success") is False:
        logger.error(
            "LIVE_ENGINE_EXIT_CLOSE_RECORD_FAILED marker=%s symbol=%s position_id=%s result=%s",
            _MARKER,
            symbol,
            pid,
            result,
        )
        return False
    auto_exit._HIGH_WATER.pop(auto_exit._position_key(pos), None)
    logger.critical(
        "LIVE_ENGINE_EXIT_FILL_CONFIRMED marker=%s symbol=%s position_id=%s reason=%s order_id=%s status=%s",
        _MARKER,
        symbol,
        pid,
        pending.reason,
        oid,
        broker_v25._status(merged),
    )
    return True


def _scan_engine(engine: Any) -> int:
    ledger = getattr(engine, "trade_ledger", None)
    broker = getattr(engine, "broker_client", None) or getattr(engine, "broker", None)
    if ledger is None or broker is None:
        return 0
    try:
        positions = ledger.get_open_positions()
    except Exception as exc:
        logger.warning("LIVE_ENGINE_EXIT_OPEN_POSITIONS_FAILED marker=%s err=%s", _MARKER, exc)
        return 0

    closed = 0
    now = time.monotonic()
    active = getattr(engine, "active_exit_orders", None)
    if not isinstance(active, set):
        active = set()
        setattr(engine, "active_exit_orders", active)

    for raw in positions or []:
        pos = raw if isinstance(raw, dict) else dict(getattr(raw, "__dict__", {}) or {})
        symbol = auto_exit._sym(pos.get("symbol"))
        pid = str(pos.get("position_id") or symbol)
        key = _key(engine, pos)
        pending = _PENDING.get(key)
        if pending is not None:
            status_payload = broker_v25._query_order(broker, pending.order, symbol)
            if _mark_engine_closed(engine, pending, status_payload):
                closed += 1
                _PENDING.pop(key, None)
                active.discard(symbol)
                active.discard(pid)
                continue
            if broker_v25._is_terminal_failure(status_payload):
                logger.error(
                    "LIVE_ENGINE_EXIT_TERMINAL_FAILURE marker=%s symbol=%s order_id=%s status=%s",
                    _MARKER,
                    symbol,
                    broker_v25._order_id(pending.order),
                    broker_v25._status(status_payload),
                )
                _PENDING.pop(key, None)
                active.discard(symbol)
                active.discard(pid)
                continue
            if now < pending.deadline:
                logger.info(
                    "LIVE_ENGINE_EXIT_FILL_PENDING marker=%s symbol=%s order_id=%s status=%s",
                    _MARKER,
                    symbol,
                    broker_v25._order_id(pending.order),
                    broker_v25._status(status_payload) or "unknown",
                )
                continue
            logger.error(
                "LIVE_ENGINE_EXIT_FILL_TIMEOUT marker=%s symbol=%s order_id=%s action=reconcile_before_retry",
                _MARKER,
                symbol,
                broker_v25._order_id(pending.order),
            )
            _PENDING.pop(key, None)
            active.discard(symbol)
            active.discard(pid)
            continue

        if not symbol or symbol in active or pid in active:
            continue
        entry = auto_exit._entry_price(pos)
        qty = auto_exit._quantity(pos)
        if entry <= 0 or qty <= 0:
            logger.warning(
                "LIVE_ENGINE_EXIT_SKIPPED_UNVERIFIED_POSITION marker=%s symbol=%s entry=%.8f qty=%.8f no_cost_basis_fabrication=true",
                _MARKER,
                symbol,
                entry,
                qty,
            )
            continue
        market = auto_exit._price(broker, symbol)
        if market <= 0:
            logger.warning("LIVE_ENGINE_EXIT_PRICE_UNAVAILABLE marker=%s symbol=%s", _MARKER, symbol)
            continue
        hit, reason, target = broker_v25._trigger(broker, pos, market)
        if not hit:
            continue

        active.add(symbol)
        active.add(pid)
        logger.critical(
            "LIVE_ENGINE_EXIT_TRIGGER marker=%s symbol=%s position_id=%s reason=%s target=%.8f market=%.8f entry=%.8f qty=%.8f",
            _MARKER,
            symbol,
            pid,
            reason,
            target,
            market,
            entry,
            qty,
        )
        order = auto_exit._exit_order(broker, pos, market)
        if not isinstance(order, dict) or not auto_exit._ok(order):
            logger.error(
                "LIVE_ENGINE_EXIT_SUBMIT_FAILED marker=%s symbol=%s position_id=%s error=%s",
                _MARKER,
                symbol,
                pid,
                order,
            )
            active.discard(symbol)
            active.discard(pid)
            continue

        pending_exit = broker_v25.PendingExit(
            broker=broker,
            position=dict(pos),
            order=dict(order),
            reason=reason,
            market=market,
            created_at=now,
            deadline=now + max(5.0, broker_v25._f(os.environ.get("NIJA_EXIT_FILL_CONFIRM_TIMEOUT_S"), 30.0)),
        )
        if _mark_engine_closed(engine, pending_exit, order):
            closed += 1
            active.discard(symbol)
            active.discard(pid)
            continue
        if not broker_v25._order_id(order):
            logger.error(
                "LIVE_ENGINE_EXIT_UNCONFIRMED_NO_ORDER_ID marker=%s symbol=%s position_id=%s status=%s position_remains_open=true",
                _MARKER,
                symbol,
                pid,
                broker_v25._status(order) or "unknown",
            )
            active.discard(symbol)
            active.discard(pid)
            continue
        _PENDING[key] = pending_exit
        logger.warning(
            "LIVE_ENGINE_EXIT_SUBMITTED_AWAITING_FILL marker=%s symbol=%s position_id=%s order_id=%s status=%s",
            _MARKER,
            symbol,
            pid,
            broker_v25._order_id(order),
            broker_v25._status(order) or "accepted",
        )
    return closed


def _patch_engine(module: Any) -> bool:
    original_result = bool(_ORIGINAL_PATCH_ENGINE(module))
    cls = getattr(module, "ExecutionEngine", None)
    if not isinstance(cls, type):
        return original_result
    cls.scan_stop_loss_take_profit_once = _scan_engine
    cls.start_stop_loss_take_profit_monitor = auto_exit._register_engine
    setattr(cls, _PATCHED_CLASS_ATTR, True)
    logger.warning(
        "LIVE_ENGINE_PROFIT_EXIT_CLASS_PATCHED marker=%s class=%s future_import_safe=true",
        _MARKER,
        cls.__name__,
    )
    return True


def _patch_loaded_execution_engines() -> None:
    for module_name in ("bot.execution_engine", "execution_engine"):
        module = sys.modules.get(module_name)
        if module is not None:
            _patch_engine(module)


def install_import_hook() -> bool:
    global _INSTALLED
    auto_exit._scan_once = _scan_engine
    auto_exit._patch_engine = _patch_engine
    _patch_loaded_execution_engines()
    if _INSTALLED:
        return True
    _INSTALLED = True
    logger.critical(
        "LIVE_ENGINE_PROFIT_EXIT_V25_INSTALLED marker=%s fill_confirmed=true fee_aware=true future_import_safe=true",
        _MARKER,
    )
    return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "install",
    "install_import_hook",
    "_scan_engine",
    "_mark_engine_closed",
    "_patch_engine",
]
