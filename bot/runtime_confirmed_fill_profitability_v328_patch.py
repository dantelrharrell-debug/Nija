"""Confirmed-fill profitability authority v328.

Profitability accounting is only as reliable as execution provenance.  The
legacy multi-broker direct dispatch path could promote an order ACK to a fill by
substituting ``price_hint_usd`` for the exchange fill price and the requested
notional for filled notional.  That can create false positions, false P&L and
perfect-looking 0-bps execution observations.

v328 is monotonic hardening:
* ordinary direct crypto and dedicated equity execution require an exchange
  order id plus fill-specific price and filled-notional/volume evidence;
* pending/open/partial ACKs are reconciliation conditions, never fills;
* request/quote/price-hint values are never promoted to execution facts;
* the v325/v326 Kraken short path is preserved and remains terminal-strict;
* confirmed fill slippage is measured against the pre-trade reference when one
  exists; unknown slippage is recorded as unknown (-1), not perfect 0 bps;
* no broker/risk/writer/nonce/kill-switch/capital/position/exit gates are
  weakened or bypassed.
"""
from __future__ import annotations

from contextvars import ContextVar
from functools import wraps
import importlib
import inspect
import logging
import math
import os
import threading
from typing import Any, Mapping, Optional

LOGGER = logging.getLogger("nija.runtime_confirmed_fill_profitability_v328")
MARKER = "20260831-runtime-confirmed-fill-profitability-v328"
_PATCH_ATTR = "_nija_runtime_confirmed_fill_profitability_v328"
_LOCK = threading.RLock()
_MEASURED_SLIPPAGE_BPS: ContextVar[Optional[float]] = ContextVar(
    "nija_v328_measured_slippage_bps", default=None
)

_REJECT_STATUSES = {
    "error", "failed", "rejected", "canceled", "cancelled", "skipped",
    "blocked", "unfilled", "expired",
}
_PENDING_STATUSES = {
    "pending", "open", "new", "accepted", "ack", "acknowledged", "submitted",
    "partially_filled", "partial", "working", "queued",
}
_FILLED_STATUSES = {"filled", "closed", "complete", "completed", "executed"}


def _f(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value if value is not None else default)
    except (TypeError, ValueError, OverflowError):
        return default
    return out if math.isfinite(out) else default


def _norm(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _order_id(result: Mapping[str, Any]) -> str:
    return str(
        result.get("order_id")
        or result.get("id")
        or result.get("exchange_order_id")
        or result.get("txid")
        or ""
    ).strip()


def _fill_price(result: Mapping[str, Any]) -> float:
    # Deliberately exclude generic ``price``.  It is often an order/quote price,
    # not proof of execution.
    for key in (
        "filled_price", "average_filled_price", "average_fill_price", "avg_price",
        "executed_price", "execution_price",
    ):
        value = _f(result.get(key), 0.0)
        if value > 0.0:
            return value
    return 0.0


def _filled_usd(result: Mapping[str, Any], fill_price: float) -> float:
    for key in (
        "filled_size_usd", "filled_value", "filled_notional", "executed_value",
        "executed_notional", "filled_quote", "filled_quote_amount",
    ):
        value = _f(result.get(key), 0.0)
        if value > 0.0:
            return value
    for key in (
        "filled_volume", "filled_size", "executed_qty", "executed_quantity",
        "filled_quantity",
    ):
        qty = _f(result.get(key), 0.0)
        if qty > 0.0 and fill_price > 0.0:
            return qty * fill_price
    return 0.0


def _reference_price(metadata: Mapping[str, Any] | None, limit_price: Any = None) -> float:
    limit = _f(limit_price, 0.0)
    if limit > 0.0:
        return limit
    meta = metadata if isinstance(metadata, Mapping) else {}
    for key in (
        "reference_price_usd", "expected_price", "expected_entry_price",
        "price_hint_usd", "pretrade_price", "decision_price",
    ):
        value = _f(meta.get(key), 0.0)
        if value > 0.0:
            return value
    return 0.0


def _capture_slippage(side: str, fill_price: float, reference_price: float) -> Optional[float]:
    if fill_price <= 0.0 or reference_price <= 0.0:
        _MEASURED_SLIPPAGE_BPS.set(None)
        return None
    if _norm(side) in {"sell", "short"}:
        raw = (reference_price - fill_price) / reference_price * 10_000.0
    else:
        raw = (fill_price - reference_price) / reference_price * 10_000.0
    # Routing models score execution *cost*. Favorable price improvement is not
    # a penalty; retain zero rather than a negative value.
    measured = max(0.0, min(5_000.0, raw))
    _MEASURED_SLIPPAGE_BPS.set(measured)
    LOGGER.info(
        "CONFIRMED_FILL_V328_SLIPPAGE marker=%s side=%s reference=%.10f fill=%.10f adverse_bps=%.4f",
        MARKER, side, reference_price, fill_price, measured,
    )
    return measured


def _normalize_dict_fill(
    result: Mapping[str, Any],
    *,
    symbol: str,
    side: str,
) -> tuple[float, float]:
    status = _norm(result.get("status") or result.get("state"))
    error = str(result.get("error") or result.get("message") or "").strip()
    if status in _REJECT_STATUSES:
        raise RuntimeError(error or status or "exchange_order_rejected")

    oid = _order_id(result)
    price = _fill_price(result)
    filled_usd = _filled_usd(result, price)

    if status in _PENDING_STATUSES:
        if oid:
            raise RuntimeError(
                f"ACK timeout pending reconciliation order_id={oid} status={status} symbol={symbol} side={side}"
            )
        raise RuntimeError(
            f"Order pending without exchange order id status={status} symbol={symbol} side={side}"
        )

    if not oid:
        raise RuntimeError(
            f"Exchange response lacks real order id; fill not proven: {dict(result)!r}"
        )
    if price <= 0.0 or filled_usd <= 0.0:
        raise RuntimeError(
            f"ACK timeout pending reconciliation order_id={oid} status={status or 'unknown'} "
            "reason=fill_specific_price_or_notional_missing"
        )

    # A missing status is accepted only when explicit fill-specific fields prove
    # price and quantity/notional.  A known non-final status was rejected above.
    if status and status not in _FILLED_STATUSES:
        raise RuntimeError(
            f"ACK timeout pending reconciliation order_id={oid} status={status} reason=nonfinal_status"
        )

    LOGGER.critical(
        "CONFIRMED_FILL_V328_ACCEPTED marker=%s symbol=%s side=%s order_id=%s status=%s "
        "fill_price=%.10f filled_usd=%.8f price_hint_promoted=false requested_notional_promoted=false",
        MARKER, symbol, side, oid, status or "implicit_fill_fields", price, filled_usd,
    )
    return price, filled_usd


def _submit_direct(broker: Any, symbol: str, side: str, size_usd: float, metadata: Mapping[str, Any]):
    submit = getattr(broker, "place_market_order", None)
    if not callable(submit):
        submit = getattr(broker, "execute_order", None)
    if not callable(submit):
        submit = getattr(broker, "place_order", None)
    if not callable(submit):
        raise RuntimeError(f"Broker {broker!r} has no market-order submit method")

    trace_id = str(metadata.get("decision_trace_id") or metadata.get("trace_id") or "")
    submit_kwargs = {"size_type": "quote"}
    if trace_id:
        try:
            sig = inspect.signature(submit)
            if "decision_trace_id" in sig.parameters:
                submit_kwargs["decision_trace_id"] = trace_id
        except (TypeError, ValueError):
            pass
    try:
        return submit(symbol, side, float(size_usd), **submit_kwargs)
    except TypeError:
        try:
            return submit(symbol=symbol, side=side, quantity=float(size_usd), **submit_kwargs)
        except TypeError:
            return submit(symbol, side, float(size_usd))


def _patch_router() -> bool:
    try:
        module = importlib.import_module("bot.multi_broker_execution_router")
        cls = getattr(module, "MultiBrokerExecutionRouter", None)
    except Exception:
        return False
    if cls is None:
        return False

    current_direct = getattr(cls, "_dispatch_direct_broker_market_order", None)
    if not callable(current_direct):
        return False
    if not getattr(current_direct, _PATCH_ATTR, False):
        @wraps(current_direct)
        def strict_direct(
            broker: Any,
            *,
            symbol: str,
            side: str,
            size_usd: float,
            metadata: Mapping[str, Any],
        ) -> tuple[float, float]:
            meta = dict(metadata or {})
            # v326 already performs a stricter terminal AddOrder assertion and
            # confirmed-fill check for proof-gated Kraken margin shorts.
            if meta.get("kraken_margin_short_v325") is True:
                price, filled = current_direct(
                    broker,
                    symbol=symbol,
                    side=side,
                    size_usd=size_usd,
                    metadata=meta,
                )
                _capture_slippage(side, price, _reference_price(meta))
                return price, filled

            result = _submit_direct(broker, symbol, side, size_usd, meta)
            if isinstance(result, tuple):
                # Tuple-only returns lack exchange order-id/status provenance.
                # Permit only an explicitly attested compatibility response.
                if not bool(meta.get("exchange_fill_confirmed")) or not str(meta.get("exchange_order_id") or "").strip():
                    raise RuntimeError(
                        "Tuple broker response lacks confirmed-fill provenance; exchange_fill_confirmed/order_id required"
                    )
                price = _f(result[0] if len(result) > 0 else 0.0)
                filled = _f(result[1] if len(result) > 1 else 0.0)
                if price <= 0.0 or filled <= 0.0:
                    raise RuntimeError("Attested tuple broker response lacks positive fill evidence")
            elif isinstance(result, Mapping):
                price, filled = _normalize_dict_fill(result, symbol=symbol, side=side)
            else:
                raise RuntimeError(f"Unsupported broker order response: {result!r}")
            _capture_slippage(side, price, _reference_price(meta))
            return price, filled

        setattr(strict_direct, _PATCH_ATTR, True)
        setattr(strict_direct, "__wrapped__", current_direct)
        cls._dispatch_direct_broker_market_order = staticmethod(strict_direct)

    current_equity = getattr(cls, "_dispatch_dedicated_equity_client", None)
    if not callable(current_equity):
        return False
    if not getattr(current_equity, _PATCH_ATTR, False):
        @wraps(current_equity)
        def strict_equity(
            symbol: str,
            side: str,
            size_usd: float,
            order_type: str = "MARKET",
            limit_price: Optional[float] = None,
            broker_name: str = "",
            metadata: Optional[Mapping[str, Any]] = None,
        ) -> tuple[float, float]:
            meta = dict(metadata or {})
            broker = meta.get("broker_client") or meta.get("broker_adapter")
            if broker is None:
                raise RuntimeError(
                    f"BROKER_ASSET_CLASS_API_UNAVAILABLE: {broker_name} has no dedicated brokerage client"
                )
            submit = getattr(broker, "place_equity_order", None)
            if not callable(submit):
                submit = getattr(broker, "submit_equity_order", None)
            if not callable(submit):
                raise RuntimeError(
                    f"BROKER_ASSET_CLASS_API_UNAVAILABLE: {broker_name} client lacks dedicated equity submit"
                )
            result = submit(
                symbol=symbol,
                side=side,
                notional_usd=float(size_usd),
                order_type=str(order_type or "MARKET").upper(),
                limit_price=limit_price,
            )
            if isinstance(result, tuple):
                if not bool(meta.get("exchange_fill_confirmed")) or not str(meta.get("exchange_order_id") or "").strip():
                    raise RuntimeError(
                        "Tuple brokerage response lacks confirmed-fill provenance; exchange_fill_confirmed/order_id required"
                    )
                price = _f(result[0] if len(result) > 0 else 0.0)
                filled = _f(result[1] if len(result) > 1 else 0.0)
                if price <= 0.0 or filled <= 0.0:
                    raise RuntimeError("Attested tuple brokerage response lacks positive fill evidence")
            elif isinstance(result, Mapping):
                price, filled = _normalize_dict_fill(result, symbol=symbol, side=side)
            else:
                raise RuntimeError(f"Unsupported brokerage order response: {result!r}")
            _capture_slippage(side, price, _reference_price(meta, limit_price))
            return price, filled

        setattr(strict_equity, _PATCH_ATTR, True)
        setattr(strict_equity, "__wrapped__", current_equity)
        cls._dispatch_dedicated_equity_client = staticmethod(strict_equity)

    current_route = getattr(cls, "route", None)
    if not callable(current_route):
        return False
    if not getattr(current_route, _PATCH_ATTR, False):
        @wraps(current_route)
        def route_with_slippage_scope(self, *args, **kwargs):
            token = _MEASURED_SLIPPAGE_BPS.set(None)
            try:
                return current_route(self, *args, **kwargs)
            finally:
                _MEASURED_SLIPPAGE_BPS.reset(token)

        setattr(route_with_slippage_scope, _PATCH_ATTR, True)
        setattr(route_with_slippage_scope, "__wrapped__", current_route)
        cls.route = route_with_slippage_scope
    return True


def _patch_performance_scorer() -> bool:
    try:
        module = importlib.import_module("bot.broker_performance_scorer")
        cls = getattr(module, "BrokerPerformanceScorer", None)
    except Exception:
        return False
    if cls is None:
        return False
    current = getattr(cls, "record_order_result", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    @wraps(current)
    def record_truthful_slippage(
        self,
        broker: str,
        success: bool,
        latency_ms: float = 0.0,
        slippage_bps: float = 0.0,
        error: Optional[str] = None,
    ) -> None:
        measured = _MEASURED_SLIPPAGE_BPS.get()
        supplied = _f(slippage_bps, 0.0)
        # Existing callers use 0.0 as "unknown".  A genuinely measured exact
        # zero is represented by the context value 0.0 and remains valid.
        slip = float(measured) if measured is not None else (supplied if supplied > 0.0 else -1.0)
        error_lower = (error or "").lower()
        obs = module.OrderObservation(
            success=bool(success),
            latency_ms=max(0.0, _f(latency_ms, 0.0)),
            slippage_bps=slip,
            rejected=module._is_rejection_error(error_lower),
            connected=not module._is_connectivity_error(error_lower),
        )
        with self._lock:
            if broker not in self._states:
                self._states[broker] = module._BrokerState(
                    broker, self._window, self._ema_alpha
                )
            self._states[broker].record(obs)
        module.logger.debug(
            "BrokerPerformanceScorer v328 | %s | success=%s latency=%.0fms slippage=%s",
            broker,
            success,
            latency_ms,
            f"{slip:.4f}bps" if slip >= 0.0 else "unknown",
        )

    setattr(record_truthful_slippage, _PATCH_ATTR, True)
    setattr(record_truthful_slippage, "__wrapped__", current)
    cls.record_order_result = record_truthful_slippage
    return True


def _patch_execution_quality_filter() -> bool:
    try:
        module = importlib.import_module("bot.execution_quality_filter")
        cls = getattr(module, "ExecutionQualityFilter", None)
    except Exception:
        return False
    if cls is None:
        return False
    current = getattr(cls, "record_execution", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    @wraps(current)
    def record_truthful_execution(
        self,
        symbol: str,
        broker: str,
        success: bool,
        slippage_bps: float = 0.0,
        latency_ms: float = 0.0,
    ) -> None:
        measured = _MEASURED_SLIPPAGE_BPS.get()
        supplied = _f(slippage_bps, 0.0)
        slip = float(measured) if measured is not None else (supplied if supplied > 0.0 else -1.0)
        obs = module.ExecutionObservation(
            timestamp=module.datetime.now(module.timezone.utc).isoformat(),
            success=bool(success),
            slippage_bps=slip,
            latency_ms=max(0.0, _f(latency_ms, 0.0)),
        )
        with self._lock:
            key = (symbol, broker)
            if key not in self._histories:
                if len(self._histories) >= module.MAX_TRACKED_PAIRS:
                    oldest = min(
                        self._histories,
                        key=lambda k: self._histories[k].last_access_ts,
                    )
                    del self._histories[oldest]
                self._histories[key] = module._PairHistory(self._window)
            self._histories[key].record(obs)
        module.logger.debug(
            "ExecQuality v328 recorded: %s@%s success=%s slip=%s lat=%.0fms",
            symbol,
            broker,
            success,
            f"{slip:.4f}bps" if slip >= 0.0 else "unknown",
            latency_ms,
        )

    setattr(record_truthful_execution, _PATCH_ATTR, True)
    setattr(record_truthful_execution, "__wrapped__", current)
    cls.record_execution = record_truthful_execution
    return True


def install_import_hook() -> bool:
    with _LOCK:
        outcomes = {
            "strict_router_fill": _patch_router(),
            "truthful_broker_slippage": _patch_performance_scorer(),
            "truthful_pair_slippage": _patch_execution_quality_filter(),
        }
        ready = all(outcomes.values())
        os.environ["NIJA_RUNTIME_CONFIRMED_FILL_PROFITABILITY_V328_READY"] = "1" if ready else "0"
        if ready:
            LOGGER.critical(
                "RUNTIME_CONFIRMED_FILL_PROFITABILITY_V328_READY marker=%s outcomes=%s "
                "ack_not_fill=true price_hint_not_fill=true requested_notional_not_fill=true "
                "confirmed_slippage_learning=true unknown_slippage_not_zero=true "
                "kraken_short_terminal_preserved=true safety_gates_bypassed=false",
                MARKER, outcomes,
            )
        else:
            LOGGER.critical(
                "RUNTIME_CONFIRMED_FILL_PROFITABILITY_V328_INCOMPLETE marker=%s outcomes=%s fail_closed_existing_gates_preserved=true",
                MARKER, outcomes,
            )
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER", "install", "install_import_hook", "_normalize_dict_fill",
    "_capture_slippage", "_reference_price",
]
