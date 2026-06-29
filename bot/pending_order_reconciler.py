from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

logger = logging.getLogger("nija.pending_order_reconciler")

DEFAULT_PENDING_ORDER_TIMEOUT_S = 90.0
TERMINAL_STATUSES = {"filled", "closed", "canceled", "cancelled", "expired", "rejected", "failed"}
LIVE_STATUSES = {"open", "pending", "accepted", "new", "partially_filled", "partially-filled"}


@dataclass
class PendingOrderReconcileResult:
    cleared: int = 0
    filled: int = 0
    cancelled: int = 0
    still_pending: int = 0
    errors: int = 0


def _now() -> float:
    return time.time()


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _order_id(order: Any) -> Optional[str]:
    if isinstance(order, dict):
        return str(order.get("id") or order.get("order_id") or order.get("client_order_id") or order.get("cl_ord_id") or "") or None
    return str(getattr(order, "id", None) or getattr(order, "order_id", None) or getattr(order, "client_order_id", None) or getattr(order, "cl_ord_id", None) or "") or None


def _order_symbol(order: Any) -> str:
    if isinstance(order, dict):
        return str(order.get("symbol") or order.get("pair") or order.get("product_id") or order.get("instId") or "UNKNOWN")
    return str(getattr(order, "symbol", None) or getattr(order, "pair", None) or getattr(order, "product_id", None) or getattr(order, "instId", None) or "UNKNOWN")


def _order_status(order: Any) -> str:
    if isinstance(order, dict):
        return str(order.get("status") or order.get("state") or "pending").lower()
    return str(getattr(order, "status", None) or getattr(order, "state", None) or "pending").lower()


def _order_created_at(order: Any) -> float:
    if isinstance(order, dict):
        raw = order.get("created_at_ts") or order.get("created_ts") or order.get("timestamp") or order.get("created_at")
    else:
        raw = getattr(order, "created_at_ts", None) or getattr(order, "created_ts", None) or getattr(order, "timestamp", None) or getattr(order, "created_at", None)
    return _as_float(raw, _now())


def _set_status(order: Any, status: str) -> None:
    if isinstance(order, dict):
        order["status"] = status
        return
    try:
        setattr(order, "status", status)
    except Exception:
        return


def _query_order_status(broker: Any, order: Any, order_id: Optional[str]) -> Optional[str]:
    if broker is None or not order_id:
        return None
    for method_name in ("get_order_status", "query_order", "get_order", "fetch_order"):
        method = getattr(broker, method_name, None)
        if not callable(method):
            continue
        try:
            response = method(order_id)
            if isinstance(response, dict):
                return str(response.get("status") or response.get("state") or "").lower() or None
            status = getattr(response, "status", None) or getattr(response, "state", None)
            if status:
                return str(status).lower()
        except Exception as exc:
            logger.warning("PENDING_ORDER_RECONCILE_STATUS_ERROR order_id=%s method=%s error=%s", order_id, method_name, exc)
            return None
    return None


def _cancel_order(broker: Any, order: Any, order_id: Optional[str]) -> bool:
    if broker is None or not order_id:
        return False
    symbol = _order_symbol(order)
    for method_name in ("cancel_order", "cancel_open_order", "cancel", "cancel_order_by_id"):
        method = getattr(broker, method_name, None)
        if not callable(method):
            continue
        try:
            try:
                method(order_id, symbol=symbol)
            except TypeError:
                method(order_id)
            return True
        except Exception as exc:
            logger.warning("PENDING_ORDER_CANCEL_ERROR order_id=%s symbol=%s method=%s error=%s", order_id, symbol, method_name, exc)
            return False
    return False


def _release_symbol_lock(owner: Any, symbol: str) -> None:
    for attr in ("_pending_symbols", "pending_symbols", "symbol_locks", "_symbol_locks"):
        locks = getattr(owner, attr, None)
        if hasattr(locks, "discard"):
            try:
                locks.discard(symbol)
                return
            except Exception:
                pass
        if isinstance(locks, dict):
            try:
                locks.pop(symbol, None)
                return
            except Exception:
                pass


def reconcile_stale_pending_orders(
    *,
    owner: Any,
    broker: Any = None,
    pending_orders: Optional[Iterable[Any]] = None,
    timeout_s: float = DEFAULT_PENDING_ORDER_TIMEOUT_S,
) -> PendingOrderReconcileResult:
    """Cancel/release stale pending orders so symbols do not block forever.

    This helper is defensive and broker-agnostic: if a broker supports order-query
    or cancel methods, they are used; otherwise NIJA still releases local stale
    pending locks after the timeout and emits explicit warning telemetry.
    """
    result = PendingOrderReconcileResult()
    orders = list(pending_orders or getattr(owner, "pending_orders", None) or getattr(owner, "_pending_orders", None) or [])
    now = _now()

    for order in orders:
        order_id = _order_id(order)
        symbol = _order_symbol(order)
        status = _order_status(order)
        age = max(0.0, now - _order_created_at(order))

        if status in TERMINAL_STATUSES:
            result.cleared += 1
            _release_symbol_lock(owner, symbol)
            logger.warning("STALE_PENDING_ORDER_CLEARED terminal order_id=%s symbol=%s status=%s age=%.1fs", order_id, symbol, status, age)
            continue

        if status not in LIVE_STATUSES and age < timeout_s:
            result.still_pending += 1
            continue

        if age < timeout_s:
            result.still_pending += 1
            continue

        live_status = _query_order_status(broker, order, order_id)
        if live_status in {"filled", "closed"}:
            _set_status(order, live_status)
            _release_symbol_lock(owner, symbol)
            result.filled += 1
            logger.warning("STALE_PENDING_ORDER_CLEARED filled order_id=%s symbol=%s status=%s age=%.1fs", order_id, symbol, live_status, age)
            continue

        cancelled = _cancel_order(broker, order, order_id)
        if cancelled:
            result.cancelled += 1
            _set_status(order, "cancelled")
        else:
            result.cleared += 1
            _set_status(order, "expired_local_clear")
        _release_symbol_lock(owner, symbol)
        logger.warning(
            "STALE_PENDING_ORDER_CLEARED order_id=%s symbol=%s previous_status=%s live_status=%s cancelled=%s age=%.1fs",
            order_id,
            symbol,
            status,
            live_status or "unknown",
            cancelled,
            age,
        )

    return result
