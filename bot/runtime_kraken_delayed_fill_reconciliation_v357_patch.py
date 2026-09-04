"""Kraken delayed confirmed-fill reconciliation v357.

Fresh production evidence on 2026-09-04 showed Kraken order
OZMGFF-7RNH5-6I4AYM with a real exchange txid and later status=filled, while the
immediate order-status payload still lacked fill-specific price/notional.  v328
correctly refused to promote that ACK/status to a fill.  Later authenticated
Kraken trade history rebuilt the PLATFORM ETH cost basis and authoritative
position, but there was no order->fill handoff back into v328/v346 execution
proof.

v357 adds only a read-only delayed reconciliation step before v328 normalizes a
Kraken order result.  A result is enriched only when it has a real Kraken order
id and either:

* QueryOrders returns that exact order in a final state with positive ``vol_exec``
  and ``cost``; or
* the result/order query is final and TradesHistory contains one or more rows
  whose ``ordertxid`` exactly equals that order id, with positive executed volume
  and cost/price.

Position appearance, requested notional, price hints, market price, ACK, pending
status, unrelated trade rows, and generic connectivity are never fill proof.
This patch performs no order mutation and does not change writer/nonce/risk/
capital/position-sync/ECEL/broker-health/minimum-order/kill-switch/rejection or
protective-exit policy.
"""
from __future__ import annotations

import importlib
import logging
import math
import os
import threading
from collections.abc import Mapping
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_kraken_delayed_fill_reconciliation_v357")
MARKER = "20260904-runtime-kraken-delayed-fill-reconciliation-v357"
RELEASE_ID = "20260904-runtime-convergence-v357"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_DELAYED_FILL_RECONCILIATION_V357_READY"
_PATCH_ATTR = "_nija_kraken_delayed_fill_reconciliation_v357"
_LOCK = threading.RLock()
_FINAL = {"filled", "closed", "complete", "completed", "executed"}


def _f(value: Any) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return out if math.isfinite(out) and out > 0.0 else 0.0


def _norm(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _is_kraken(broker: Any) -> bool:
    btype = getattr(broker, "broker_type", None)
    label = str(getattr(btype, "value", btype) or "").lower()
    cls = type(broker).__name__.lower()
    return "kraken" in label or "kraken" in cls


def _order_id(result: Mapping[str, Any]) -> str:
    return str(
        result.get("order_id")
        or result.get("id")
        or result.get("exchange_order_id")
        or result.get("txid")
        or ""
    ).strip()


def _status(result: Mapping[str, Any]) -> str:
    return _norm(result.get("status") or result.get("state"))


def _monitoring_category() -> Any:
    """Return the canonical Kraken monitoring enum used by private reads.

    ``KrakenBroker._kraken_private_call`` expects ``KrakenAPICategory`` and
    several rate/fairness wrappers read ``category.value``.  Passing a plain
    string here therefore fails before QueryOrders/TradesHistory can execute.
    Resolve the same enum used by the broker and by v304/v297; if unavailable,
    omit the category rather than inventing a string substitute.
    """
    try:
        module = importlib.import_module("bot.broker_manager")
        enum_cls = getattr(module, "KrakenAPICategory", None)
        return getattr(enum_cls, "MONITORING", None) if enum_cls is not None else None
    except Exception:
        return None


def _private_read(broker: Any, method: str, params: dict[str, Any]) -> dict[str, Any]:
    """Issue one authenticated read through the broker's canonical private path."""
    caller = getattr(broker, "_kraken_private_call", None)
    if callable(caller):
        category = _monitoring_category()
        if category is not None:
            try:
                value = caller(method, dict(params), category=category)
            except TypeError:
                value = caller(method, dict(params))
        else:
            value = caller(method, dict(params))
        return dict(value) if isinstance(value, Mapping) else {}

    caller = getattr(broker, "_kraken_api_call", None)
    if callable(caller):
        value = caller(method, dict(params))
        return dict(value) if isinstance(value, Mapping) else {}

    api = getattr(broker, "api", None) or getattr(broker, "kraken_api", None)
    query = getattr(api, "query_private", None)
    if callable(query):
        value = query(method, dict(params))
        return dict(value) if isinstance(value, Mapping) else {}
    return {}


def _query_order_row(broker: Any, order_id: str) -> dict[str, Any]:
    try:
        payload = _private_read(broker, "QueryOrders", {"txid": order_id, "trades": True})
    except Exception as exc:
        LOGGER.info(
            "KRAKEN_FILL_V357_QUERY_ORDER_DEFERRED marker=%s order_id=%s error=%s:%s fail_closed=true",
            MARKER, order_id, type(exc).__name__, exc,
        )
        return {}
    if payload.get("error"):
        return {}
    result = payload.get("result")
    if not isinstance(result, Mapping):
        return {}
    row = result.get(order_id)
    return dict(row) if isinstance(row, Mapping) else {}


def _query_order_fill(row: Mapping[str, Any]) -> tuple[str, float, float, float]:
    status = _norm(row.get("status") or row.get("state"))
    qty = _f(row.get("vol_exec") or row.get("filled_volume") or row.get("filled_size"))
    cost = _f(row.get("cost") or row.get("filled_cost") or row.get("filled_notional"))
    if status not in _FINAL or qty <= 0.0 or cost <= 0.0:
        return status, 0.0, 0.0, 0.0
    return status, cost / qty, qty, cost


def _trade_history_fill(
    broker: Any,
    *,
    order_id: str,
    side: str,
) -> tuple[float, float, float, int]:
    """Aggregate only authenticated Kraken trades tied to the exact order id."""
    try:
        payload = _private_read(broker, "TradesHistory", {"type": "all", "trades": True})
    except Exception as exc:
        LOGGER.info(
            "KRAKEN_FILL_V357_TRADE_HISTORY_DEFERRED marker=%s order_id=%s error=%s:%s fail_closed=true",
            MARKER, order_id, type(exc).__name__, exc,
        )
        return 0.0, 0.0, 0.0, 0
    if payload.get("error"):
        return 0.0, 0.0, 0.0, 0
    result = payload.get("result")
    trades = result.get("trades") if isinstance(result, Mapping) else None
    if not isinstance(trades, Mapping):
        return 0.0, 0.0, 0.0, 0

    wanted_side = _norm(side)
    total_qty = 0.0
    total_cost = 0.0
    matches = 0
    for row in trades.values():
        if not isinstance(row, Mapping):
            continue
        if str(row.get("ordertxid") or "").strip() != order_id:
            continue
        row_side = _norm(row.get("type") or row.get("side"))
        if wanted_side in {"buy", "sell"} and row_side and row_side != wanted_side:
            continue
        qty = _f(row.get("vol") or row.get("volume") or row.get("qty"))
        price = _f(row.get("price"))
        cost = _f(row.get("cost"))
        if cost <= 0.0 and qty > 0.0 and price > 0.0:
            cost = qty * price
        if qty <= 0.0 or cost <= 0.0:
            continue
        total_qty += qty
        total_cost += cost
        matches += 1

    if matches <= 0 or total_qty <= 0.0 or total_cost <= 0.0:
        return 0.0, 0.0, 0.0, 0
    return total_cost / total_qty, total_qty, total_cost, matches


def _has_fill_specific(result: Mapping[str, Any]) -> bool:
    price = 0.0
    for key in (
        "filled_price", "average_filled_price", "average_fill_price", "avg_price",
        "executed_price", "execution_price",
    ):
        price = _f(result.get(key))
        if price > 0.0:
            break
    if price <= 0.0:
        return False
    for key in (
        "filled_size_usd", "filled_value", "filled_notional", "executed_value",
        "executed_notional", "filled_quote", "filled_quote_amount",
    ):
        if _f(result.get(key)) > 0.0:
            return True
    for key in (
        "filled_volume", "filled_size", "executed_qty", "executed_quantity", "filled_quantity",
    ):
        if _f(result.get(key)) > 0.0:
            return True
    return False


def _enrich_kraken_final_order(
    broker: Any,
    result: Any,
    *,
    symbol: str,
    side: str,
) -> Any:
    if not _is_kraken(broker) or not isinstance(result, Mapping):
        return result
    enriched = dict(result)
    oid = _order_id(enriched)
    if not oid or _has_fill_specific(enriched):
        return enriched

    original_status = _status(enriched)
    order_row = _query_order_row(broker, oid)
    queried_status, price, qty, filled_usd = _query_order_fill(order_row)
    final_status = queried_status if queried_status in _FINAL else original_status

    if price > 0.0 and qty > 0.0 and filled_usd > 0.0:
        enriched.update(
            status=queried_status,
            filled_price=price,
            filled_size=qty,
            filled_size_usd=filled_usd,
            kraken_query_order_reconciled=True,
        )
        LOGGER.critical(
            "KRAKEN_FILL_V357_QUERY_ORDER_RECONCILED marker=%s order_id=%s symbol=%s side=%s "
            "status=%s filled_qty=%.12f fill_price=%.10f filled_usd=%.8f exact_order_match=true "
            "read_only=true ack_not_fill=true requested_notional_promoted=false market_price_promoted=false "
            "position_appearance_not_proof=true execution_proof_fabricated=false safety_gates_bypassed=false",
            MARKER, oid, symbol, side, queried_status, qty, price, filled_usd,
        )
        return enriched

    # TradesHistory may expose the execution legs even when QueryOrders omits
    # cost/average-fill fields. Require a final order state from either the
    # original broker result or the exact QueryOrders row before using them.
    if final_status not in _FINAL:
        return enriched
    price, qty, filled_usd, matches = _trade_history_fill(
        broker, order_id=oid, side=side
    )
    if price <= 0.0 or qty <= 0.0 or filled_usd <= 0.0 or matches <= 0:
        return enriched

    enriched.update(
        status=final_status,
        filled_price=price,
        filled_size=qty,
        filled_size_usd=filled_usd,
        kraken_trade_history_reconciled=True,
        kraken_trade_history_match_count=matches,
    )
    LOGGER.critical(
        "KRAKEN_FILL_V357_TRADE_HISTORY_RECONCILED marker=%s order_id=%s symbol=%s side=%s "
        "status=%s matched_trades=%d filled_qty=%.12f fill_price=%.10f filled_usd=%.8f "
        "ordertxid_exact_match=true read_only=true ack_not_fill=true requested_notional_promoted=false "
        "market_price_promoted=false position_appearance_not_proof=true execution_proof_fabricated=false "
        "safety_gates_bypassed=false",
        MARKER, oid, symbol, side, final_status, matches, qty, price, filled_usd,
    )
    return enriched


def _patch_v328_submit() -> bool:
    module = importlib.import_module("bot.runtime_confirmed_fill_profitability_v328_patch")
    current = getattr(module, "_submit_direct", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def submit_v357(broker: Any, symbol: str, side: str, size_usd: float, metadata: Mapping[str, Any]):
        result = current(broker, symbol, side, size_usd, metadata)
        return _enrich_kraken_final_order(
            broker, result, symbol=symbol, side=side
        )

    setattr(submit_v357, _PATCH_ATTR, True)
    setattr(submit_v357, "__wrapped__", current)
    module._submit_direct = submit_v357
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_kraken_delayed_fill_reconciliation_v357"] = _READY_FLAG
        return True
    except Exception:
        return False


def install_import_hook() -> bool:
    with _LOCK:
        submit_ok = manifest_ok = False
        try:
            submit_ok = _patch_v328_submit()
            manifest_ok = _register_manifest()
        except Exception:
            LOGGER.exception(
                "RUNTIME_KRAKEN_DELAYED_FILL_RECONCILIATION_V357_INSTALL_ERROR marker=%s fail_closed=true",
                MARKER,
            )
        ready = bool(submit_ok and manifest_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        log = LOGGER.critical if ready else LOGGER.error
        log(
            "RUNTIME_KRAKEN_DELAYED_FILL_RECONCILIATION_V357_%s marker=%s ready=%s "
            "queryorders_exact_order_required=true trade_history_ordertxid_exact_match=true "
            "final_status_required=true positive_fill_quantity_required=true positive_fill_cost_required=true "
            "position_appearance_not_fill=true ack_not_fill=true requested_notional_promoted=false "
            "market_price_promoted=false writer_nonce_risk_capital_position_killswitch_ecel_broker_health_"
            "minimum_order_fill_gates_unchanged=true protective_exits_unchanged=true forced_trade=false "
            "forced_activation=false execution_proof_fabricated=false safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY", MARKER, str(ready).lower(),
        )
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER", "RELEASE_ID", "install", "install_import_hook",
    "_enrich_kraken_final_order", "_trade_history_fill", "_query_order_fill",
]
