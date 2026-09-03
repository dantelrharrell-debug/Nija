"""Canonical dispatch contract helpers for market-order submission.

This module is the single source of truth for two execution invariants that
production proved were missing:

1. **Base-size sells.**  Every venue that NIJA trades (Coinbase Advanced Trade
   in particular) requires a closing SELL to carry an explicit *base-asset*
   quantity.  Forwarding a USD notional where a base size is required raised
   ``TypeError: market_order_sell() missing 1 required positional argument:
   'base_size'`` inside ``execution_pipeline`` — before the exchange was ever
   contacted.

2. **Failure classification.**  A local ``TypeError`` / argument-binding error
   / any failure raised *before* the broker adapter reached the venue is an
   ``INTERNAL_DISPATCH_FAILURE``.  It is **not** an ``EXCHANGE_REJECTION`` and
   must never be added to the exchange rejection window that drives the
   kill switch.

The helpers here are intentionally pure and side-effect free so they can be
unit tested with mocked brokers only.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Mapping, Optional, Tuple

logger = logging.getLogger("nija.execution_dispatch_contract")

#: Marker embedded in error strings for failures that happened locally, before
#: the order was handed to (and acknowledged/rejected by) the venue.
INTERNAL_DISPATCH_FAILURE = "INTERNAL_DISPATCH_FAILURE"

#: Marker for a position that cannot be closed because the authoritative owned
#: quantity is below the venue minimum.  The position is preserved for later
#: reconciliation; it is never rounded up and never submitted.
BELOW_MINIMUM_NON_EXECUTABLE = "BELOW_MINIMUM_EXIT_NON_EXECUTABLE"

#: Metadata keys that may carry an authoritative owned base quantity.
_OWNED_QTY_KEYS: Tuple[str, ...] = (
    "verified_position_quantity",
    "owned_base_qty",
    "owned_quantity",
    "position_quantity",
    "base_quantity",
)

#: Metadata keys that may carry an already-compiled base quantity.
_COMPILED_QTY_KEYS: Tuple[str, ...] = (
    "units",
    "compiled_base_size",
    "base_size",
)

_PRICE_KEYS: Tuple[str, ...] = (
    "price_hint_usd",
    "reference_price_usd",
    "pretrade_price",
    "market_price",
)


class InternalDispatchFailure(RuntimeError):
    """Raised for a local failure that occurred before broker submission.

    Callers must classify this as :data:`INTERNAL_DISPATCH_FAILURE` and must
    not record an exchange rejection sample for it.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(f"{INTERNAL_DISPATCH_FAILURE}: {reason}")
        self.reason = reason


class NonExecutableExitQuantity(InternalDispatchFailure):
    """Raised when the owned quantity is below the venue minimum.

    The exit is not submitted, the quantity is never increased to the venue
    minimum, no short position is created, and the position is preserved for
    later reconciliation.
    """

    def __init__(self, *, symbol: str, owned_qty: float, minimum_qty: float, reason: str) -> None:
        self.symbol = symbol
        self.owned_qty = float(owned_qty)
        self.minimum_qty = float(minimum_qty)
        super().__init__(
            f"{BELOW_MINIMUM_NON_EXECUTABLE} symbol={symbol} owned_qty={owned_qty!r} "
            f"minimum_qty={minimum_qty!r} reason={reason}"
        )


def is_internal_dispatch_failure(error: Any) -> bool:
    """Return ``True`` when *error* describes a local pre-dispatch failure."""
    if isinstance(error, InternalDispatchFailure):
        return True
    text = str(error or "").strip().lower()
    if not text:
        return False
    return (
        INTERNAL_DISPATCH_FAILURE.lower() in text
        or BELOW_MINIMUM_NON_EXECUTABLE.lower() in text
        or "missing 1 required positional argument" in text
        or "missing required positional argument" in text
        or "unexpected keyword argument" in text
        or "takes no arguments" in text
        or "positional arguments but" in text
    )


def _f(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value if value is not None else default)
    except (TypeError, ValueError, OverflowError):
        return default
    return out if math.isfinite(out) else default


def is_closing_sell(side: str, metadata: Mapping[str, Any]) -> bool:
    """Return ``True`` when the order reduces/closes an existing long position."""
    if str(side or "").strip().lower() != "sell":
        return False
    meta = metadata or {}
    if bool(meta.get("closing_position")) or bool(meta.get("reduce_only")):
        return True
    if str(meta.get("position_effect") or "").strip().lower() in {"close", "reduce"}:
        return True
    return str(meta.get("intent_type") or "").strip().lower() in {"exit", "reduce"}


def resolve_owned_base_quantity(metadata: Mapping[str, Any]) -> Optional[float]:
    """Return the authoritative owned base quantity from *metadata*, if any."""
    meta = metadata or {}
    for key in _OWNED_QTY_KEYS:
        if key in meta:
            qty = _f(meta.get(key), 0.0)
            if qty > 0:
                return qty
    return None


def resolve_reference_price(metadata: Mapping[str, Any]) -> float:
    """Return the first positive reference price found in *metadata*."""
    meta = metadata or {}
    for key in _PRICE_KEYS:
        price = _f(meta.get(key), 0.0)
        if price > 0:
            return price
    return 0.0


def resolve_sell_base_quantity(
    *,
    symbol: str,
    size_usd: float,
    metadata: Mapping[str, Any],
    minimum_qty: Optional[float] = None,
) -> float:
    """Resolve the explicit, validated base quantity for a closing SELL.

    The result is the smaller of the already-compiled quantity and the
    authoritative owned quantity.  It can never exceed the owned quantity, and
    it is never rounded or increased up to ``minimum_qty``.

    Raises:
        NonExecutableExitQuantity: owned quantity is below ``minimum_qty``.
        InternalDispatchFailure: no base quantity could be derived.
    """
    meta = dict(metadata or {})
    owned = resolve_owned_base_quantity(meta)

    compiled: Optional[float] = None
    for key in _COMPILED_QTY_KEYS:
        candidate = _f(meta.get(key), 0.0)
        if candidate > 0:
            compiled = candidate
            break

    if compiled is None:
        price = resolve_reference_price(meta)
        notional = _f(size_usd, 0.0)
        if price > 0 and notional > 0:
            compiled = notional / price

    candidates = [q for q in (compiled, owned) if q is not None and q > 0]
    if not candidates:
        raise InternalDispatchFailure(
            f"sell_base_quantity_unresolved symbol={symbol} size_usd={size_usd!r} "
            "no compiled units, owned quantity or reference price available"
        )

    # Hard oversell guard: a closing SELL can never exceed the owned quantity.
    quantity = min(candidates)

    min_qty = _f(minimum_qty, 0.0)
    if min_qty > 0 and quantity < min_qty:
        raise NonExecutableExitQuantity(
            symbol=symbol,
            owned_qty=owned if owned is not None else quantity,
            minimum_qty=min_qty,
            reason="owned quantity below venue minimum; exit withheld for reconciliation",
        )

    if quantity <= 0:
        raise InternalDispatchFailure(
            f"sell_base_quantity_non_positive symbol={symbol} quantity={quantity!r}"
        )
    return quantity


__all__ = [
    "BELOW_MINIMUM_NON_EXECUTABLE",
    "INTERNAL_DISPATCH_FAILURE",
    "InternalDispatchFailure",
    "NonExecutableExitQuantity",
    "is_closing_sell",
    "is_internal_dispatch_failure",
    "resolve_owned_base_quantity",
    "resolve_reference_price",
    "resolve_sell_base_quantity",
]
