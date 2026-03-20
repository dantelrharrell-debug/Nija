"""
NIJA Execution Confirmation Layer
==================================

Wraps order placement with mandatory fill confirmation, partial-fill
detection, and automatic retry for unfilled/partially-filled orders.

Responsibilities
----------------
1. **Order confirmed** — poll broker until the order reaches a terminal
   state (``filled``, ``closed``, ``canceled``) or a timeout expires.
2. **Filled vs partially filled** — return a rich ``ConfirmationResult``
   that distinguishes full fills from partial fills.
3. **Retry if not filled** — if the order is partially or un-filled, the
   remaining quantity is re-submitted up to ``max_retries`` times with
   exponential back-off (with jitter).

Usage
-----
::

    from bot.execution_confirmation_layer import get_execution_confirmation_layer

    ecl = get_execution_confirmation_layer()
    result = ecl.place_and_confirm(
        broker=kraken_broker,
        symbol="XBTUSD",
        side="buy",
        size=0.001,
        size_type="base",
        order_fn=kraken_broker.place_market_order,
    )

    if result.is_success:
        logger.info(f"Order filled: {result.filled_size} @ {result.avg_price}")
    elif result.is_partial:
        logger.warning(f"Partial fill: {result.filled_pct:.1f}%")
    else:
        logger.error(f"Order not filled: {result.error}")
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("nija.execution.confirmation")

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

# How long (seconds) to wait for Kraken to transition an order to a
# terminal state before declaring it "not filled".
DEFAULT_CONFIRMATION_TIMEOUT_S: float = 30.0

# Seconds between consecutive status polls.
DEFAULT_POLL_INTERVAL_S: float = 2.0

# Maximum number of retries for un-filled / partially-filled orders.
DEFAULT_MAX_FILL_RETRIES: int = 3

# Base delay (seconds) for exponential back-off between fill retries.
DEFAULT_RETRY_BASE_DELAY_S: float = 2.0

# Fraction of delay added as random jitter (0 → 30 % of the delay).
_JITTER_FRACTION: float = 0.30

# Acceptable fill deviation before flagging as "partial" (1 %).
DEFAULT_PARTIAL_FILL_TOLERANCE: float = 0.01


# ---------------------------------------------------------------------------
# Data-classes
# ---------------------------------------------------------------------------


class FillStatus(Enum):
    """Terminal fill outcomes."""
    FILLED = "filled"           # 100% (or within tolerance) filled
    PARTIAL = "partial"         # Partially filled
    UNFILLED = "unfilled"       # Zero fill
    TIMEOUT = "timeout"         # Confirmation timed out
    ERROR = "error"             # Unexpected error


@dataclass
class ConfirmationResult:
    """
    Rich result object returned by :meth:`ExecutionConfirmationLayer.place_and_confirm`.

    All monetary quantities are in the *base* currency of the traded pair
    unless noted otherwise.
    """

    # --- Identity ---
    symbol: str
    side: str                           # "buy" / "sell"
    order_id: Optional[str] = None

    # --- Fill details ---
    status: FillStatus = FillStatus.UNFILLED
    expected_size: float = 0.0
    filled_size: float = 0.0
    avg_price: Optional[float] = None
    cost_usd: Optional[float] = None    # Quote-currency cost of the fill

    # --- Retry metadata ---
    attempts: int = 0
    retries_used: int = 0

    # --- Timing ---
    placed_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None

    # --- Error detail ---
    error: Optional[str] = None

    # --- Raw broker responses ---
    raw_responses: list = field(default_factory=list)

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def filled_pct(self) -> float:
        """Percentage of expected_size that was actually filled."""
        if self.expected_size <= 0:
            return 0.0
        return (self.filled_size / self.expected_size) * 100.0

    @property
    def is_success(self) -> bool:
        return self.status == FillStatus.FILLED

    @property
    def is_partial(self) -> bool:
        return self.status == FillStatus.PARTIAL

    @property
    def remaining_size(self) -> float:
        return max(0.0, self.expected_size - self.filled_size)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "order_id": self.order_id,
            "status": self.status.value,
            "expected_size": self.expected_size,
            "filled_size": self.filled_size,
            "filled_pct": self.filled_pct,
            "avg_price": self.avg_price,
            "cost_usd": self.cost_usd,
            "attempts": self.attempts,
            "retries_used": self.retries_used,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class ExecutionConfirmationLayer:
    """
    Wraps any broker's *place_order* call with:

    * Mandatory fill confirmation (poll until terminal state or timeout).
    * Partial-fill detection.
    * Automatic retry of the unfilled remainder with jitter back-off.
    """

    def __init__(
        self,
        confirmation_timeout_s: float = DEFAULT_CONFIRMATION_TIMEOUT_S,
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        max_fill_retries: int = DEFAULT_MAX_FILL_RETRIES,
        retry_base_delay_s: float = DEFAULT_RETRY_BASE_DELAY_S,
        partial_fill_tolerance: float = DEFAULT_PARTIAL_FILL_TOLERANCE,
    ) -> None:
        self.confirmation_timeout_s = confirmation_timeout_s
        self.poll_interval_s = poll_interval_s
        self.max_fill_retries = max_fill_retries
        self.retry_base_delay_s = retry_base_delay_s
        self.partial_fill_tolerance = partial_fill_tolerance

        logger.info(
            "ExecutionConfirmationLayer initialised — "
            f"timeout={confirmation_timeout_s}s  poll={poll_interval_s}s  "
            f"max_retries={max_fill_retries}  base_delay={retry_base_delay_s}s"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def place_and_confirm(
        self,
        broker: Any,
        symbol: str,
        side: str,
        size: float,
        order_fn: Optional[Callable] = None,
        size_type: str = "base",
        **order_kwargs: Any,
    ) -> ConfirmationResult:
        """
        Place an order and wait for fill confirmation.  Retries the
        unfilled remainder on partial / zero fills.

        Parameters
        ----------
        broker:
            Broker adapter instance (must expose ``get_order_status`` if
            available, otherwise the layer infers fill from the initial
            response).
        symbol:
            Trading pair, e.g. ``"XBTUSD"`` or ``"BTC-USD"``.
        side:
            ``"buy"`` or ``"sell"``.
        size:
            Order quantity in *base* currency (or quote if
            ``size_type="quote"``).
        order_fn:
            Callable that places the order and returns a broker response
            dict.  Defaults to ``broker.place_market_order`` if omitted.
        size_type:
            ``"base"`` (default) or ``"quote"``.
        **order_kwargs:
            Extra keyword arguments forwarded to ``order_fn``.

        Returns
        -------
        ConfirmationResult
        """
        if order_fn is None:
            order_fn = getattr(broker, "place_market_order", None)
            if order_fn is None:
                return ConfirmationResult(
                    symbol=symbol,
                    side=side,
                    status=FillStatus.ERROR,
                    error="broker has no place_market_order method and no order_fn provided",
                )

        result = ConfirmationResult(
            symbol=symbol,
            side=side,
            expected_size=size,
            placed_at=datetime.utcnow(),
        )

        remaining = size
        delay = self.retry_base_delay_s

        for attempt in range(1, self.max_fill_retries + 2):  # +1 for initial attempt
            result.attempts = attempt

            logger.info(
                f"🔄 [{symbol}] {side.upper()} attempt {attempt} — "
                f"size={remaining:.8f} {size_type}"
            )

            # ── Place the order ──────────────────────────────────────
            try:
                response = order_fn(symbol, side, remaining, size_type=size_type, **order_kwargs)
            except Exception as exc:
                logger.error(f"❌ [{symbol}] Order placement failed (attempt {attempt}): {exc}")
                result.error = str(exc)
                result.status = FillStatus.ERROR
                result.raw_responses.append({"attempt": attempt, "error": str(exc)})
                break

            result.raw_responses.append({"attempt": attempt, "response": response})

            if not response:
                logger.error(f"❌ [{symbol}] Empty response from broker (attempt {attempt})")
                result.error = "Empty broker response"
                result.status = FillStatus.ERROR
                break

            # Extract order_id from broker response (multiple formats)
            order_id = self._extract_order_id(response)
            if order_id and not result.order_id:
                result.order_id = order_id

            # ── Confirm the fill ─────────────────────────────────────
            filled, avg_price = self._wait_for_fill(broker, order_id, response)

            result.filled_size += filled
            if avg_price and result.avg_price is None:
                result.avg_price = avg_price

            logger.info(
                f"📊 [{symbol}] Confirmed fill: {filled:.8f} "
                f"(cumulative: {result.filled_size:.8f} / {size:.8f})"
            )

            # ── Check fill completeness ──────────────────────────────
            remaining = size - result.filled_size
            fill_ratio = result.filled_size / size if size > 0 else 1.0

            if fill_ratio >= (1.0 - self.partial_fill_tolerance):
                result.status = FillStatus.FILLED
                result.confirmed_at = datetime.utcnow()
                logger.info(f"✅ [{symbol}] FULL FILL confirmed ({result.filled_pct:.1f}%)")
                break

            if filled > 0:
                result.status = FillStatus.PARTIAL
                logger.warning(
                    f"⚠️ [{symbol}] PARTIAL FILL: {result.filled_pct:.1f}% "
                    f"— remaining={remaining:.8f}"
                )
            else:
                result.status = FillStatus.UNFILLED
                logger.warning(
                    f"⚠️ [{symbol}] ZERO FILL on attempt {attempt} "
                    f"— remaining={remaining:.8f}"
                )

            # ── Should we retry? ─────────────────────────────────────
            if attempt > self.max_fill_retries:
                logger.error(
                    f"❌ [{symbol}] Max fill retries ({self.max_fill_retries}) reached. "
                    f"Final fill: {result.filled_pct:.1f}%"
                )
                break

            result.retries_used += 1

            # Exponential back-off with jitter
            jitter = random.uniform(0, _JITTER_FRACTION * delay)
            sleep_time = delay + jitter
            logger.info(f"🕐 [{symbol}] Retrying remaining {remaining:.8f} in {sleep_time:.1f}s …")
            time.sleep(sleep_time)
            delay = min(delay * 2, 30.0)

        # Final status housekeeping
        if result.status not in (FillStatus.FILLED, FillStatus.PARTIAL):
            if result.filled_size > 0:
                result.status = FillStatus.PARTIAL
            else:
                result.status = FillStatus.UNFILLED

        logger.info(
            f"📋 [{symbol}] Confirmation summary: status={result.status.value}  "
            f"filled={result.filled_pct:.1f}%  attempts={result.attempts}  "
            f"retries={result.retries_used}"
        )
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _wait_for_fill(
        self,
        broker: Any,
        order_id: Optional[str],
        initial_response: Dict[str, Any],
    ) -> tuple[float, Optional[float]]:
        """
        Poll broker for terminal fill status.

        Returns (filled_size, avg_price).
        """
        # If no order_id, infer from initial response only
        if not order_id:
            return self._parse_fill_from_response(initial_response)

        get_status = getattr(broker, "get_order_status", None)
        if get_status is None:
            # Broker doesn't support status polling; use initial response
            return self._parse_fill_from_response(initial_response)

        deadline = time.monotonic() + self.confirmation_timeout_s
        checks = 0

        while time.monotonic() < deadline:
            checks += 1
            try:
                status_resp = get_status(order_id)
            except Exception as exc:
                logger.warning(f"Status poll {checks} failed for {order_id}: {exc}")
                time.sleep(self.poll_interval_s)
                continue

            if not status_resp:
                time.sleep(self.poll_interval_s)
                continue

            order_status = str(status_resp.get("status", "")).lower()

            # Terminal states
            if order_status in ("filled", "closed", "complete", "done"):
                return self._parse_fill_from_response(status_resp)

            if order_status in ("canceled", "cancelled", "expired"):
                logger.warning(f"Order {order_id} was {order_status}")
                return self._parse_fill_from_response(status_resp)

            # Still open / pending — keep polling
            logger.debug(
                f"  ⏳ [{order_id}] status={order_status}  "
                f"check={checks}  t_remaining={deadline - time.monotonic():.1f}s"
            )
            time.sleep(self.poll_interval_s)

        logger.warning(
            f"⏰ Order {order_id} confirmation timed out after "
            f"{self.confirmation_timeout_s}s — using last known state"
        )
        # Return best-effort parse from initial response on timeout
        return self._parse_fill_from_response(initial_response)

    @staticmethod
    def _parse_fill_from_response(
        response: Dict[str, Any],
    ) -> tuple[float, Optional[float]]:
        """
        Extract (filled_size, avg_price) from a broker response dict.

        Handles multiple broker response formats (Kraken, Coinbase, generic).
        """
        if not response:
            return 0.0, None

        filled: float = 0.0
        avg_price: Optional[float] = None

        # Kraken: result → {txid: {vol_exec, price, ...}}
        result = response.get("result", {})
        if isinstance(result, dict):
            for _txid, order_data in result.items():
                if isinstance(order_data, dict):
                    try:
                        vol_exec = float(order_data.get("vol_exec", 0) or 0)
                        filled = max(filled, vol_exec)
                        price_raw = order_data.get("price") or order_data.get("avg_price")
                        if price_raw:
                            avg_price = float(price_raw)
                    except (TypeError, ValueError):
                        pass

        # Coinbase / generic: top-level fields
        for field_name in ("filled_size", "executed_qty", "size", "volume"):
            raw = response.get(field_name)
            if raw is not None:
                try:
                    val = float(raw)
                    if val > 0:
                        filled = max(filled, val)
                        break
                except (TypeError, ValueError):
                    pass

        for price_field in ("avg_price", "average_price", "fill_price", "price"):
            raw = response.get(price_field)
            if raw is not None and avg_price is None:
                try:
                    avg_price = float(raw)
                except (TypeError, ValueError):
                    pass

        return filled, avg_price

    @staticmethod
    def _extract_order_id(response: Dict[str, Any]) -> Optional[str]:
        """Extract order ID from broker response (multi-format)."""
        if not response:
            return None

        # Kraken: result.txid = [id]
        result = response.get("result", {})
        if isinstance(result, dict):
            txid = result.get("txid", [])
            if txid:
                return txid[0] if isinstance(txid, list) else str(txid)

        # Coinbase / generic
        for field_name in ("order_id", "id", "orderId", "client_order_id"):
            val = response.get(field_name)
            if val:
                return str(val)

        return None


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_INSTANCE: Optional[ExecutionConfirmationLayer] = None


def get_execution_confirmation_layer(
    confirmation_timeout_s: float = DEFAULT_CONFIRMATION_TIMEOUT_S,
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
    max_fill_retries: int = DEFAULT_MAX_FILL_RETRIES,
    retry_base_delay_s: float = DEFAULT_RETRY_BASE_DELAY_S,
    partial_fill_tolerance: float = DEFAULT_PARTIAL_FILL_TOLERANCE,
) -> ExecutionConfirmationLayer:
    """Return (or create) the singleton :class:`ExecutionConfirmationLayer`."""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = ExecutionConfirmationLayer(
            confirmation_timeout_s=confirmation_timeout_s,
            poll_interval_s=poll_interval_s,
            max_fill_retries=max_fill_retries,
            retry_base_delay_s=retry_base_delay_s,
            partial_fill_tolerance=partial_fill_tolerance,
        )
    return _INSTANCE
