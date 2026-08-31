"""Kraken short-margin terminal integrity v326.

Completes the v325 proof-gated short path at the actual broker boundary.

The canonical multi-broker router historically forwarded only symbol/side/notional
for direct market orders.  That is correct for spot, but it would drop leverage
and margin intent from a v325 short before reaching Kraken.  Kraken's legacy
adapter also intentionally falls back to spot if margin admission fails.  For a
short *entry* that fallback is unsafe: an ordinary spot sell is not equivalent
to opening a short.

v326 is therefore fail-closed and narrowly scoped to metadata carrying
``kraken_margin_short_v325=true``:
* preserve the exact account id across the router's ThreadPool boundary;
* forward leverage/reduce_only/margin_mode to Kraken's market-order method;
* require sell + leverage 2x/3x at the final AddOrder call;
* if the legacy adapter tries to fall back to spot, block before the exchange;
* require confirmed fill evidence before reporting success; an ACK/pending order
  is returned as a retryable reconciliation condition, never a fabricated fill.

All ordinary buys/sells, exits/reductions, derivatives and other venues retain
existing behavior.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import replace
from functools import wraps
import importlib
import inspect
import logging
import math
import os
import threading
from typing import Any, Mapping

LOGGER = logging.getLogger("nija.runtime_kraken_short_terminal_integrity_v326")
MARKER = "20260831-runtime-kraken-short-terminal-integrity-v326"
_PATCH_ATTR = "_nija_runtime_kraken_short_terminal_integrity_v326"
_LOCK = threading.RLock()
_TERMINAL_SHORT_REQUIRED: ContextVar[bool] = ContextVar(
    "nija_v326_terminal_short_required", default=False
)


def _f(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value if value is not None else default)
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed if math.isfinite(parsed) else default


def _norm(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _is_v325_short_metadata(metadata: Mapping[str, Any] | None) -> bool:
    return bool(isinstance(metadata, Mapping) and metadata.get("kraken_margin_short_v325") is True)


def _is_kraken_broker(broker: Any) -> bool:
    if broker is None:
        return False
    candidates = (
        getattr(getattr(broker, "broker_type", None), "value", None),
        getattr(broker, "broker_type", None),
        getattr(broker, "NAME", None),
        getattr(broker, "name", None),
        type(broker).__name__,
    )
    return any("kraken" in _norm(value) for value in candidates if value is not None)


def _patch_pipeline_account_provenance() -> bool:
    """Carry exact account provenance into metadata before thread dispatch."""
    try:
        module = importlib.import_module("bot.execution_pipeline")
        cls = getattr(module, "ExecutionPipeline", None)
    except Exception:
        return False
    if cls is None:
        return False
    original = getattr(cls, "_dispatch", None)
    if not callable(original):
        return False
    if getattr(original, _PATCH_ATTR, False):
        return True

    @wraps(original)
    def dispatch_with_account_provenance(self, request, *args, **kwargs):
        metadata = dict(getattr(request, "metadata", {}) or {})
        if _is_v325_short_metadata(metadata):
            account_id = str(getattr(request, "account_id", "") or "").strip()
            if not account_id:
                return self._deny(
                    request,
                    __import__("time").monotonic(),
                    "KrakenShortTerminalV326 deny: margin_account_id_missing",
                )
            metadata["kraken_margin_account_id"] = account_id
            request = replace(request, metadata=metadata)
        return original(self, request, *args, **kwargs)

    setattr(dispatch_with_account_provenance, _PATCH_ATTR, True)
    setattr(dispatch_with_account_provenance, "__wrapped__", original)
    cls._dispatch = dispatch_with_account_provenance
    return True


def _normalize_confirmed_fill(
    result: Any,
    *,
    symbol: str,
    side: str,
    size_usd: float,
) -> tuple[float, float]:
    if not isinstance(result, dict):
        raise RuntimeError(f"V326 unsupported Kraken short response: {result!r}")
    status = _norm(result.get("status") or result.get("state"))
    error = str(result.get("error") or result.get("message") or "").strip()
    if status in {"error", "failed", "rejected", "canceled", "cancelled", "blocked", "skipped"}:
        raise RuntimeError(error or status or "kraken_short_rejected")

    order_id = str(
        result.get("order_id") or result.get("id") or result.get("exchange_order_id") or ""
    ).strip()
    fill_price = _f(
        result.get("filled_price")
        or result.get("average_filled_price")
        or result.get("average_fill_price")
        or result.get("avg_price")
        or result.get("price")
    )
    filled_volume = _f(result.get("filled_volume") or result.get("filled_size") or result.get("volume"))
    filled_usd = _f(
        result.get("filled_size_usd")
        or result.get("filled_value")
        or result.get("notional_usd")
    )
    if filled_usd <= 0.0 and fill_price > 0.0 and filled_volume > 0.0:
        filled_usd = fill_price * filled_volume

    if status == "filled" and order_id and fill_price > 0.0 and filled_usd > 0.0:
        LOGGER.critical(
            "KRAKEN_SHORT_TERMINAL_V326_CONFIRMED_FILL marker=%s symbol=%s side=%s order_id=%s "
            "fill_price=%.8f filled_usd=%.2f",
            MARKER, symbol, side, order_id, fill_price, filled_usd,
        )
        return fill_price, filled_usd

    if order_id:
        # This wording intentionally contains ACK timeout so the existing pipeline
        # classifies it as a soft/reconciliation condition rather than a hard
        # exchange rejection.  The order may have filled after the broker's first
        # QueryOrders check, so it must not be retried as a fresh short blindly.
        raise RuntimeError(
            f"ACK timeout pending reconciliation for Kraken margin short order_id={order_id} status={status or 'unknown'}"
        )
    raise RuntimeError(
        f"Kraken margin short lacked confirmed order/fill evidence status={status or 'unknown'} error={error or 'none'}"
    )


def _patch_multi_broker_terminal_dispatch() -> bool:
    try:
        module = importlib.import_module("bot.multi_broker_execution_router")
        cls = getattr(module, "MultiBrokerExecutionRouter", None)
    except Exception:
        return False
    if cls is None:
        return False
    original = getattr(cls, "_dispatch_direct_broker_market_order", None)
    if not callable(original):
        return False
    if getattr(original, _PATCH_ATTR, False):
        return True

    @wraps(original)
    def direct_market_with_margin_integrity(
        broker: Any,
        *,
        symbol: str,
        side: str,
        size_usd: float,
        metadata: dict[str, Any],
    ) -> tuple[float, float]:
        meta = dict(metadata or {})
        if not _is_v325_short_metadata(meta):
            return original(
                broker,
                symbol=symbol,
                side=side,
                size_usd=size_usd,
                metadata=meta,
            )
        if not _is_kraken_broker(broker):
            raise RuntimeError("V326 short metadata reached non-Kraken broker")
        if _norm(side) != "sell":
            raise RuntimeError("V326 Kraken short must dispatch as sell")
        leverage = int(_f(meta.get("leverage"), 0.0))
        if leverage not in {2, 3}:
            raise RuntimeError(f"V326 Kraken short leverage invalid:{leverage}")
        if meta.get("reduce_only") is not False:
            raise RuntimeError("V326 Kraken short entry requires reduce_only=false")
        margin_mode = _norm(meta.get("margin_mode"))
        if margin_mode not in {"cross", "isolated"}:
            raise RuntimeError(f"V326 Kraken short margin_mode invalid:{margin_mode or 'missing'}")
        account_id = str(meta.get("kraken_margin_account_id") or "").strip()
        if not account_id:
            raise RuntimeError("V326 Kraken short exact account provenance missing")

        submit = getattr(broker, "place_market_order", None)
        if not callable(submit):
            raise RuntimeError("V326 Kraken broker lacks place_market_order")
        try:
            signature = inspect.signature(submit)
            accepts_var_kw = any(
                p.kind == inspect.Parameter.VAR_KEYWORD
                for p in signature.parameters.values()
            )
            required = {"leverage", "reduce_only", "margin_mode"}
            if not accepts_var_kw and not required.issubset(signature.parameters):
                raise RuntimeError(
                    "V326 Kraken adapter cannot accept required margin parameters"
                )
        except (TypeError, ValueError):
            raise RuntimeError("V326 could not verify Kraken margin submit signature")

        margin_mod = importlib.import_module("bot.kraken_margin_engine")
        margin_scope = getattr(margin_mod, "margin_account_scope", None)
        if not callable(margin_scope):
            raise RuntimeError("V326 margin_account_scope unavailable")

        LOGGER.critical(
            "KRAKEN_SHORT_TERMINAL_V326_SUBMIT_READY marker=%s account=%s symbol=%s notional=%.2f "
            "leverage=%sx sell=true reduce_only=false margin_mode=%s spot_fallback=false",
            MARKER, account_id, symbol, float(size_usd or 0.0), leverage, margin_mode,
        )
        token = _TERMINAL_SHORT_REQUIRED.set(True)
        try:
            with margin_scope(account_id, adapter=broker):
                result = submit(
                    symbol,
                    "sell",
                    float(size_usd),
                    size_type="quote",
                    leverage=leverage,
                    reduce_only=False,
                    margin_mode=margin_mode,
                )
        finally:
            _TERMINAL_SHORT_REQUIRED.reset(token)

        return _normalize_confirmed_fill(
            result,
            symbol=symbol,
            side="sell",
            size_usd=float(size_usd or 0.0),
        )

    setattr(direct_market_with_margin_integrity, _PATCH_ATTR, True)
    setattr(direct_market_with_margin_integrity, "__wrapped__", original)
    cls._dispatch_direct_broker_market_order = staticmethod(direct_market_with_margin_integrity)
    return True


def _patch_kraken_addorder_terminal_assertion() -> bool:
    try:
        module = importlib.import_module("bot.broker_integration")
        cls = getattr(module, "KrakenBrokerAdapter", None)
    except Exception:
        return False
    if cls is None:
        return False
    original = getattr(cls, "_kraken_api_call", None)
    if not callable(original):
        return False
    if getattr(original, _PATCH_ATTR, False):
        return True

    @wraps(original)
    def kraken_call_with_short_assertion(self, method: str, params=None, *args, **kwargs):
        if _TERMINAL_SHORT_REQUIRED.get() and str(method or "").strip().lower() == "addorder":
            payload = dict(params or {})
            side = _norm(payload.get("type"))
            leverage = int(_f(payload.get("leverage"), 0.0))
            if side != "sell" or leverage not in {2, 3}:
                LOGGER.critical(
                    "KRAKEN_SHORT_TERMINAL_V326_BLOCKED_SPOT_FALLBACK marker=%s side=%s leverage=%s "
                    "exchange_call_made=false safety_gates_bypassed=false",
                    MARKER, side or "missing", leverage,
                )
                raise RuntimeError(
                    "V326 fail-closed: explicit Kraken short attempted AddOrder without sell+margin leverage"
                )
            LOGGER.critical(
                "KRAKEN_SHORT_TERMINAL_V326_ADDORDER_ATTESTED marker=%s side=sell leverage=%sx spot_fallback=false",
                MARKER, leverage,
            )
        return original(self, method, params, *args, **kwargs)

    setattr(kraken_call_with_short_assertion, _PATCH_ATTR, True)
    setattr(kraken_call_with_short_assertion, "__wrapped__", original)
    cls._kraken_api_call = kraken_call_with_short_assertion
    return True


def install_import_hook() -> bool:
    with _LOCK:
        outcomes = {
            "pipeline_account_provenance": _patch_pipeline_account_provenance(),
            "router_margin_propagation": _patch_multi_broker_terminal_dispatch(),
            "kraken_addorder_assertion": _patch_kraken_addorder_terminal_assertion(),
        }
        ready = all(outcomes.values())
        os.environ["NIJA_RUNTIME_KRAKEN_SHORT_TERMINAL_V326_READY"] = "1" if ready else "0"
        if ready:
            LOGGER.critical(
                "RUNTIME_KRAKEN_SHORT_TERMINAL_INTEGRITY_V326_READY marker=%s outcomes=%s "
                "thread_account_provenance=true leverage_propagated=true spot_fallback=false "
                "addorder_margin_attested=true confirmed_fill_required=true generic_orders_unchanged=true "
                "safety_gates_bypassed=false",
                MARKER, outcomes,
            )
        else:
            LOGGER.critical(
                "RUNTIME_KRAKEN_SHORT_TERMINAL_INTEGRITY_V326_INCOMPLETE marker=%s outcomes=%s fail_closed=true",
                MARKER, outcomes,
            )
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_normalize_confirmed_fill",
]
