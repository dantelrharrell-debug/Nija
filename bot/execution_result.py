"""
NIJA Execution Result Contract
================================

Authoritative result object returned by EVERY order placement call.

Every order that touches an exchange MUST produce exactly one
``ExecutionResult`` and emit the standardised log line::

    EXECUTION_RESULT | BTC-USD | ACCEPTED | order_id=839201 | latency=142ms
    EXECUTION_RESULT | ETH-USD | REJECTED | error=INSUFFICIENT_LIQUIDITY | latency=37ms
    EXECUTION_RESULT | SOL-USD | FAILED   | error=BROKER_EXCEPTION | latency=0ms

Usage
-----
::

    from bot.execution_result import ExecutionResult, OrderStatus, log_execution_result
    from bot.pipeline_order_submitter import submit_market_order_via_pipeline
    import time

    t0 = time.monotonic()
    try:
        raw = submit_market_order_via_pipeline(
            broker=broker,
            symbol=symbol,
            side=side,
            quantity=qty,
            size_type="quote",
            strategy="ExecutionResultExample",
        )
        order_id = raw.get("order_id") or raw.get("id")
        if raw.get("status") == "error":
            result = ExecutionResult(
                status=OrderStatus.REJECTED,
                symbol=symbol,
                side=side,
                exchange_order_id=None,
                error_code=raw.get("error", "UNKNOWN_REJECTION"),
                latency_ms=int((time.monotonic() - t0) * 1000),
            )
        else:
            result = ExecutionResult(
                status=OrderStatus.ACCEPTED,
                symbol=symbol,
                side=side,
                exchange_order_id=str(order_id),
                error_code=None,
                latency_ms=int((time.monotonic() - t0) * 1000),
            )
    except Exception as exc:
        result = ExecutionResult(
            status=OrderStatus.FAILED,
            symbol=symbol,
            side=side,
            exchange_order_id=None,
            error_code=str(exc),
            latency_ms=int((time.monotonic() - t0) * 1000),
        )

    log_execution_result(result)

"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger("nija.execution_result")

# ---------------------------------------------------------------------------
# Status enum
# ---------------------------------------------------------------------------


class OrderStatus(Enum):
    """Terminal exchange-level order outcome."""
    ACCEPTED = "ACCEPTED"   # Exchange acknowledged the order (has an order_id)
    REJECTED = "REJECTED"   # Exchange explicitly refused the order
    FAILED   = "FAILED"     # Internal / network failure before exchange responded


# ---------------------------------------------------------------------------
# Canonical result dataclass
# ---------------------------------------------------------------------------


@dataclass
class ExecutionResult:
    """
    Authoritative result returned by every order placement call.

    Fields
    ------
    status:
        One of :class:`OrderStatus` — ACCEPTED, REJECTED, or FAILED.
    symbol:
        Trading pair (e.g. ``"BTC-USD"``).
    side:
        ``"buy"`` or ``"sell"``.
    exchange_order_id:
        Exchange-assigned order ID when status is ACCEPTED, otherwise ``None``.
    error_code:
        Short error token when status is REJECTED or FAILED (e.g.
        ``"INSUFFICIENT_LIQUIDITY"``), otherwise ``None``.
    latency_ms:
        Round-trip latency from submitting the order to receiving the
        exchange acknowledgement, in milliseconds.
    """

    status: OrderStatus
    symbol: str
    side: str
    exchange_order_id: Optional[str] = None
    error_code: Optional[str] = None
    latency_ms: int = 0

    # ----------------------------------------------------------------
    # Convenience properties
    # ----------------------------------------------------------------

    @property
    def is_accepted(self) -> bool:
        return self.status == OrderStatus.ACCEPTED

    @property
    def is_rejected(self) -> bool:
        return self.status == OrderStatus.REJECTED

    @property
    def is_failed(self) -> bool:
        return self.status == OrderStatus.FAILED


# ---------------------------------------------------------------------------
# Standardised log emitter
# ---------------------------------------------------------------------------


def log_execution_result(result: ExecutionResult) -> None:
    """
    Emit the canonical ``EXECUTION_RESULT`` log line for *result*.

    Format::

        EXECUTION_RESULT | <symbol> | <STATUS> | order_id=<id> | latency=<n>ms
        EXECUTION_RESULT | <symbol> | <STATUS> | error=<code>  | latency=<n>ms
    """
    parts = [
        "EXECUTION_RESULT",
        result.symbol,
        result.status.value,
    ]

    if result.exchange_order_id is not None:
        parts.append(f"order_id={result.exchange_order_id}")

    if result.error_code is not None:
        parts.append(f"error={result.error_code}")

    parts.append(f"latency={result.latency_ms}ms")

    line = " | ".join(parts)

    if result.status == OrderStatus.ACCEPTED:
        logger.info(line)
    elif result.status == OrderStatus.REJECTED:
        logger.warning(line)
    else:  # FAILED
        logger.error(line)
