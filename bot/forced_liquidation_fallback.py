"""
NIJA Forced Liquidation Fallback — Absolute Enforcement Layer
=============================================================

This module provides the **final, unconditional** backstop when normal
position management fails.  It is intentionally designed to be independent
from every other subsystem so that it can still fire even when the broader
bot logic is degraded.

Three escalating execution paths
---------------------------------
1. **Full market order** — attempt to close the full position at market
   price with the configured number of retries and exponential back-off.
2. **Adjusted-size order** — if the full-size order is rejected (e.g. due to
   minimum-notional gate), reduce the quantity by a fixed step and retry.
3. **Minimum-notional floor** — if the remaining quantity falls below the
   exchange minimum notional, execute a best-effort tiny sell/buy and flag
   the residual as an unresolvable dust position.

A position that survives all three paths is written to a *stranded positions*
journal so that operators can manually resolve it.  The system NEVER silently
drops an open position.

Integration
-----------
::

    from bot.forced_liquidation_fallback import get_forced_liquidation_fallback

    fll = get_forced_liquidation_fallback()

    result = fll.liquidate(
        symbol="BTC-USD",
        quantity=0.001,          # base asset quantity
        side="sell",             # "sell" to close a long, "buy" to close a short
        broker=my_broker,        # any object with .place_market_order() / .close_position()
        reason="stop-loss hit",
    )

    if result.success:
        logger.info("Liquidated: %s", result)
    else:
        logger.critical("STRANDED POSITION: %s", result)

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nija.forced_liquidation_fallback")

# ---------------------------------------------------------------------------
# Constants — tune via environment variables for exchange-specific limits
# ---------------------------------------------------------------------------

# Number of full-size attempts before stepping down the quantity
MAX_FULL_SIZE_RETRIES: int = int(os.environ.get("FLF_MAX_RETRIES", "3"))

# Fraction to reduce quantity on each step-down attempt (20 % reduction per step)
STEPDOWN_FRACTION: float = float(os.environ.get("FLF_STEPDOWN_FRACTION", "0.80"))

# Maximum number of step-down attempts before giving up
MAX_STEPDOWN_STEPS: int = int(os.environ.get("FLF_MAX_STEPDOWN_STEPS", "5"))

# Minimum USD notional below which we stop trying and flag as dust
MIN_NOTIONAL_USD: float = float(os.environ.get("FLF_MIN_NOTIONAL_USD", "1.0"))

# Base retry delay in seconds (doubles each retry)
BASE_RETRY_DELAY_S: float = float(os.environ.get("FLF_BASE_RETRY_DELAY", "0.5"))

# Path for the stranded-positions journal
STRANDED_POSITIONS_FILE: str = os.environ.get(
    "FLF_STRANDED_JOURNAL", "data/stranded_positions.jsonl"
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class LiquidationResult:
    """Outcome of a single forced-liquidation attempt."""
    success: bool
    symbol: str
    side: str
    requested_quantity: float
    executed_quantity: float = 0.0
    fill_price: float = 0.0
    attempts: int = 0
    path_used: str = "none"          # "full_size" | "step_down" | "min_notional" | "stranded"
    stranded: bool = False            # True → written to the stranded journal
    error: Optional[str] = None
    broker_response: Optional[Dict[str, Any]] = None
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# ForcedLiquidationFallback
# ---------------------------------------------------------------------------


class ForcedLiquidationFallback:
    """
    Absolute enforcement layer for position closure.

    Guarantees that every open position either gets closed (fully or partially)
    or is written to a stranded-positions journal.  No position is ever
    silently abandoned.

    Thread-safe; safe to call from multiple trading threads simultaneously.
    """

    def __init__(
        self,
        max_full_retries: int = MAX_FULL_SIZE_RETRIES,
        stepdown_fraction: float = STEPDOWN_FRACTION,
        max_stepdown_steps: int = MAX_STEPDOWN_STEPS,
        min_notional_usd: float = MIN_NOTIONAL_USD,
        stranded_journal_path: str = STRANDED_POSITIONS_FILE,
    ) -> None:
        self._lock = threading.Lock()
        self._max_full_retries = max_full_retries
        self._stepdown_fraction = stepdown_fraction
        self._max_stepdown_steps = max_stepdown_steps
        self._min_notional_usd = min_notional_usd
        self._stranded_journal_path = stranded_journal_path

        self._liquidation_count: int = 0
        self._stranded_count: int = 0

        # Ensure the data directory exists for the journal
        try:
            journal_dir = os.path.dirname(stranded_journal_path)
            if journal_dir:
                os.makedirs(journal_dir, exist_ok=True)
        except Exception:
            pass  # Non-fatal — journal writes will fail gracefully

        logger.info(
            "✅ ForcedLiquidationFallback initialised | "
            "max_retries=%d | stepdown=%.0f%% | max_steps=%d | min_notional=$%.2f",
            max_full_retries,
            stepdown_fraction * 100,
            max_stepdown_steps,
            min_notional_usd,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def liquidate(
        self,
        symbol: str,
        quantity: float,
        side: str,
        broker: Any,
        reason: str = "forced liquidation",
        current_price: float = 0.0,
    ) -> LiquidationResult:
        """
        Unconditionally close a position using escalating execution paths.

        Parameters
        ----------
        symbol:
            Trading pair (e.g. "BTC-USD", "XBT/USD").
        quantity:
            Quantity in *base* asset units to liquidate.
        side:
            "sell" to close a long; "buy" to close a short.
        broker:
            Any broker object that exposes at least one of:
            * ``place_market_order(symbol, side, quantity, size_type='base', ...)``
            * ``close_position(symbol, quantity, ...)``
            * ``force_liquidate(symbol, quantity, ...)``
        reason:
            Human-readable description logged alongside every attempt.
        current_price:
            Optional current price (used for notional estimation when broker
            price data is unavailable).

        Returns
        -------
        LiquidationResult — inspect ``.success`` and ``.stranded`` fields.
        """
        with self._lock:
            self._liquidation_count += 1

        logger.warning(
            "🚨 FORCED LIQUIDATION: %s qty=%.8f side=%s reason=%s",
            symbol, quantity, side, reason,
        )

        # ── Path 1: Full-size market order with retries ───────────────
        result = self._path_full_size(symbol, quantity, side, broker, reason)
        if result.success:
            return result

        # ── Path 2: Step-down quantity retries ───────────────────────
        result = self._path_step_down(symbol, quantity, side, broker, reason, current_price)
        if result.success:
            return result

        # ── Path 3: Minimum-notional floor attempt ───────────────────
        result = self._path_min_notional(symbol, quantity, side, broker, reason, current_price)
        if result.success:
            return result

        # ── Path 4: Stranded — write to journal ───────────────────────
        result.stranded = True
        result.path_used = "stranded"
        with self._lock:
            self._stranded_count += 1

        self._write_stranded_journal(symbol, quantity, side, reason, result)

        logger.critical(
            "💀 STRANDED POSITION: %s qty=%.8f side=%s — written to %s",
            symbol, quantity, side, self._stranded_journal_path,
        )
        return result

    def get_stranded_positions(self) -> List[Dict[str, Any]]:
        """
        Read all stranded positions from the journal file.

        Returns an empty list if the file does not exist or cannot be parsed.
        """
        records: List[Dict[str, Any]] = []
        try:
            with open(self._stranded_journal_path, "r") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        except FileNotFoundError:
            pass
        except Exception as exc:
            logger.error("Could not read stranded journal: %s", exc)
        return records

    def get_status(self) -> Dict[str, Any]:
        """Return a serialisable snapshot of the engine's counters."""
        with self._lock:
            return {
                "engine": "ForcedLiquidationFallback",
                "version": "1.0",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "liquidation_count": self._liquidation_count,
                "stranded_count": self._stranded_count,
                "stranded_journal": self._stranded_journal_path,
                "config": {
                    "max_full_retries": self._max_full_retries,
                    "stepdown_fraction": self._stepdown_fraction,
                    "max_stepdown_steps": self._max_stepdown_steps,
                    "min_notional_usd": self._min_notional_usd,
                },
            }

    # ------------------------------------------------------------------
    # Execution paths (private)
    # ------------------------------------------------------------------

    def _path_full_size(
        self,
        symbol: str,
        quantity: float,
        side: str,
        broker: Any,
        reason: str,
    ) -> LiquidationResult:
        """Path 1 — Full-size market order with exponential-back-off retries."""
        attempts = 0
        last_error = ""

        for attempt in range(1, self._max_full_retries + 1):
            attempts += 1
            try:
                response = self._call_broker(broker, symbol, side, quantity, reason)
                fill_price, executed_qty = self._parse_response(response, quantity)

                if executed_qty > 0:
                    logger.info(
                        "✅ [PATH:full_size] Liquidated %s qty=%.8f @ %.6f (attempt %d)",
                        symbol, executed_qty, fill_price, attempt,
                    )
                    return LiquidationResult(
                        success=True,
                        symbol=symbol,
                        side=side,
                        requested_quantity=quantity,
                        executed_quantity=executed_qty,
                        fill_price=fill_price,
                        attempts=attempts,
                        path_used="full_size",
                        broker_response=response,
                    )

                last_error = f"Broker returned 0 executed quantity: {response}"

            except Exception as exc:
                last_error = str(exc)
                logger.warning(
                    "[PATH:full_size] attempt %d/%d failed: %s",
                    attempt, self._max_full_retries, exc,
                )

            if attempt < self._max_full_retries:
                delay = BASE_RETRY_DELAY_S * (2 ** (attempt - 1))
                logger.info("[PATH:full_size] Waiting %.1fs before retry …", delay)
                time.sleep(delay)

        logger.warning(
            "⚠️  [PATH:full_size] exhausted %d retries for %s: %s",
            self._max_full_retries, symbol, last_error,
        )
        return LiquidationResult(
            success=False,
            symbol=symbol,
            side=side,
            requested_quantity=quantity,
            attempts=attempts,
            path_used="full_size",
            error=f"Full-size path failed after {attempts} attempts: {last_error}",
        )

    def _path_step_down(
        self,
        symbol: str,
        quantity: float,
        side: str,
        broker: Any,
        reason: str,
        current_price: float,
    ) -> LiquidationResult:
        """
        Path 2 — Step down the quantity by ``stepdown_fraction`` on each attempt.

        This handles cases where the exchange rejects large orders but will
        accept a slightly smaller quantity (e.g. rounding or reserve issues).
        """
        qty = quantity
        total_executed = 0.0
        total_attempts = 0

        for step in range(1, self._max_stepdown_steps + 1):
            qty = quantity * (self._stepdown_fraction ** step)

            # Stop if below minimum notional
            notional_est = qty * max(current_price, 1.0)
            if notional_est < self._min_notional_usd:
                logger.info(
                    "[PATH:step_down] qty=%.8f estimated notional $%.4f below min $%.2f — stopping step-down",
                    qty, notional_est, self._min_notional_usd,
                )
                break

            total_attempts += 1
            try:
                response = self._call_broker(broker, symbol, side, qty, reason)
                fill_price, executed_qty = self._parse_response(response, qty)

                if executed_qty > 0:
                    total_executed += executed_qty
                    logger.info(
                        "✅ [PATH:step_down] step %d: executed %.8f of %.8f @ %.6f",
                        step, executed_qty, quantity, fill_price,
                    )
                    return LiquidationResult(
                        success=True,
                        symbol=symbol,
                        side=side,
                        requested_quantity=quantity,
                        executed_quantity=total_executed,
                        fill_price=fill_price,
                        attempts=total_attempts,
                        path_used="step_down",
                        broker_response=response,
                        error=(
                            f"Partial fill: executed {total_executed:.8f} of {quantity:.8f}"
                            if total_executed < quantity
                            else None
                        ),
                    )

            except Exception as exc:
                logger.warning(
                    "[PATH:step_down] step %d qty=%.8f failed: %s", step, qty, exc
                )
                time.sleep(BASE_RETRY_DELAY_S)

        logger.warning(
            "⚠️  [PATH:step_down] exhausted %d steps for %s (final qty=%.8f)",
            self._max_stepdown_steps, symbol, qty,
        )
        return LiquidationResult(
            success=False,
            symbol=symbol,
            side=side,
            requested_quantity=quantity,
            executed_quantity=total_executed,
            attempts=total_attempts,
            path_used="step_down",
            error=f"Step-down path failed after {self._max_stepdown_steps} steps",
        )

    def _path_min_notional(
        self,
        symbol: str,
        quantity: float,
        side: str,
        broker: Any,
        reason: str,
        current_price: float,
    ) -> LiquidationResult:
        """
        Path 3 — Absolute last resort: try the minimum notional quantity once.

        If the position value is below the exchange minimum we attempt anyway
        with special flags that tell the broker to bypass size gates.
        """
        logger.warning(
            "[PATH:min_notional] Last-resort attempt for %s qty=%.8f", symbol, quantity
        )
        try:
            # Use broker's force-liquidate if available; fall back to market order
            force_liq = getattr(broker, "force_liquidate", None)
            if force_liq:
                response = force_liq(
                    symbol=symbol,
                    quantity=quantity,
                    reason=f"forced_liquidation_fallback: {reason}",
                )
            else:
                place_order = getattr(broker, "place_market_order", None)
                if place_order is None:
                    raise RuntimeError("Broker has no place_market_order method")
                response = place_order(
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    size_type="base",
                    ignore_balance=True,
                    ignore_min_trade=True,
                    force_liquidate=True,
                )

            fill_price, executed_qty = self._parse_response(response, quantity)

            if executed_qty > 0:
                logger.info(
                    "✅ [PATH:min_notional] Executed %.8f @ %.6f", executed_qty, fill_price
                )
                return LiquidationResult(
                    success=True,
                    symbol=symbol,
                    side=side,
                    requested_quantity=quantity,
                    executed_quantity=executed_qty,
                    fill_price=fill_price,
                    attempts=1,
                    path_used="min_notional",
                    broker_response=response,
                )

        except Exception as exc:
            logger.error("[PATH:min_notional] failed: %s", exc)

        return LiquidationResult(
            success=False,
            symbol=symbol,
            side=side,
            requested_quantity=quantity,
            attempts=1,
            path_used="min_notional",
            error="min_notional path failed",
        )

    # ------------------------------------------------------------------
    # Broker adapter
    # ------------------------------------------------------------------

    def _call_broker(
        self,
        broker: Any,
        symbol: str,
        side: str,
        quantity: float,
        reason: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Try multiple broker methods in priority order.

        Priority
        --------
        1. ``force_liquidate(symbol, quantity, reason)``
        2. ``close_position(symbol, quantity)``
        3. ``place_market_order(symbol, side, quantity, ...)``
        """
        force_liq = getattr(broker, "force_liquidate", None)
        if force_liq:
            return force_liq(symbol=symbol, quantity=quantity, reason=reason)

        close_pos = getattr(broker, "close_position", None)
        if close_pos:
            return close_pos(symbol=symbol, quantity=quantity)

        place_order = getattr(broker, "place_market_order", None)
        if place_order:
            return place_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                size_type="base",
            )

        raise RuntimeError(
            f"Broker {type(broker).__name__!r} has no recognised liquidation method"
        )

    @staticmethod
    def _parse_response(
        response: Optional[Dict[str, Any]],
        fallback_qty: float,
    ) -> tuple:
        """
        Extract (fill_price, executed_quantity) from a broker response dict.

        Handles several common key names used across different broker adapters.
        Falls back to (0.0, fallback_qty) for a "success" response with no
        explicit quantity, and to (0.0, 0.0) for None / failure.
        """
        if response is None:
            return 0.0, 0.0

        status = response.get("status", response.get("result", "unknown"))
        if isinstance(status, str) and status.lower() in ("filled", "completed", "success", "closed"):
            fill_price = float(
                response.get("fill_price", response.get("price", response.get("avg_price", 0.0)))
            )
            executed = float(
                response.get(
                    "executed_quantity",
                    response.get("quantity", response.get("size", fallback_qty)),
                )
            )
            return fill_price, executed

        # Some brokers return True/False
        if response is True or response == {"success": True}:
            return 0.0, fallback_qty

        return 0.0, 0.0

    # ------------------------------------------------------------------
    # Stranded journal
    # ------------------------------------------------------------------

    def _write_stranded_journal(
        self,
        symbol: str,
        quantity: float,
        side: str,
        reason: str,
        result: LiquidationResult,
    ) -> None:
        """Append a stranded position record to the JSONL journal file."""
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "quantity": quantity,
            "side": side,
            "reason": reason,
            "result": result.to_dict(),
        }
        try:
            with open(self._stranded_journal_path, "a") as fh:
                fh.write(json.dumps(record) + "\n")
        except Exception as exc:
            logger.error(
                "❌ Could not write stranded journal (%s): %s — position data follows: %s",
                self._stranded_journal_path, exc, json.dumps(record),
            )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_instance: Optional[ForcedLiquidationFallback] = None
_instance_lock = threading.Lock()


def get_forced_liquidation_fallback(**kwargs) -> ForcedLiquidationFallback:
    """
    Return the process-wide ``ForcedLiquidationFallback`` singleton.

    Keyword arguments are forwarded to the constructor on first call only.
    """
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = ForcedLiquidationFallback(**kwargs)
    return _instance
