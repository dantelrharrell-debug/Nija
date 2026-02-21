"""
DUST-TO-USD RECOVERY PIPELINE
==============================

Implements the complete four-step dust recovery workflow:

  1. Identify  – scan all broker positions and flag any below the dust
                 threshold (default $1 USD).
  2. Convert   – sell each dust position via a market order so the funds
                 become available USD.
  3. Verify    – compare the USD cash balance before and after conversion;
                 confirm it actually increased before proceeding.
  4. Resume    – re-enable trading via the Recovery Controller once the
                 account is clean.

This approach recovers all funds without risking larger positions: only
sub-threshold dust is liquidated; everything else is left untouched.

Usage::

    from bot.dust_to_usd_pipeline import DustToUsdPipeline, PipelineResult

    pipeline = DustToUsdPipeline(broker, dry_run=False)
    result = pipeline.run()
    if result.success:
        print(f"Recovered ${result.usd_recovered:.4f}")

Author: NIJA Trading Systems
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.dust_to_usd_pipeline")

# Default USD value below which a position is considered dust
DEFAULT_DUST_THRESHOLD_USD: float = 1.00


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class DustPosition:
    """A single position identified as dust."""

    symbol: str
    quantity: float
    usd_value: float
    currency: str = ""


@dataclass
class ConversionRecord:
    """Audit record for one dust-to-USD conversion attempt."""

    timestamp: str
    symbol: str
    quantity: float
    usd_value: float
    success: bool
    message: str


@dataclass
class PipelineResult:
    """Outcome of a full pipeline run."""

    success: bool
    dust_identified: int = 0
    dust_converted: int = 0
    dust_failed: int = 0
    usd_balance_before: float = 0.0
    usd_balance_after: float = 0.0
    usd_recovered: float = 0.0
    verification_passed: bool = False
    trading_resumed: bool = False
    records: List[ConversionRecord] = field(default_factory=list)
    error: str = ""
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class DustToUsdPipeline:
    """
    Four-step pipeline: Identify → Convert → Verify → Resume.

    Args:
        broker: A broker instance exposing at least::

                    broker.get_positions() -> list[dict]
                    broker.get_usd_balance() -> float
                    broker.get_current_price(symbol: str) -> float

                Optionally one of::

                    broker.close_position(symbol: str) -> dict
                    broker.place_order(symbol, side, order_type, size) -> dict

        dust_threshold_usd: Positions with a USD value strictly below this
                            amount are treated as dust. Default: $1.00.
        dry_run: When *True* all orders are simulated; no real trades are
                 placed.  The balance check is skipped in dry-run mode.
        recovery_controller: Optional RecoveryController instance.  When
                             provided the pipeline calls ``enable_trading``
                             after a successful run.  Pass *None* to skip.
    """

    def __init__(
        self,
        broker: Any,
        dust_threshold_usd: float = DEFAULT_DUST_THRESHOLD_USD,
        dry_run: bool = False,
        recovery_controller: Optional[Any] = None,
    ) -> None:
        self.broker = broker
        self.dust_threshold_usd = dust_threshold_usd
        self.dry_run = dry_run
        self.recovery_controller = recovery_controller

        logger.info("🚀 DustToUsdPipeline initialized")
        logger.info(f"   Dust threshold : ${dust_threshold_usd:.2f} USD")
        logger.info(f"   Dry-run mode   : {'YES (no real orders)' if dry_run else 'NO (live)'}")

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self) -> PipelineResult:
        """
        Execute the full Identify → Convert → Verify → Resume pipeline.

        Returns:
            :class:`PipelineResult` with full audit details.
        """
        logger.info("=" * 70)
        logger.info("💰 DUST-TO-USD RECOVERY PIPELINE STARTING")
        logger.info("=" * 70)

        result = PipelineResult(success=False)

        # ── Step 1: Identify ──────────────────────────────────────────
        dust_positions = self._identify_dust()
        result.dust_identified = len(dust_positions)

        if not dust_positions:
            logger.info("✅ Step 1 (Identify): No dust positions found – nothing to do")
            result.success = True
            result.verification_passed = True
            result = self._maybe_resume_trading(result, reason="no dust found")
            self._log_summary(result)
            return result

        logger.info(f"🔍 Step 1 (Identify): {len(dust_positions)} dust position(s) found")

        # ── Step 2: Convert ───────────────────────────────────────────
        usd_before = self._get_usd_balance()
        result.usd_balance_before = usd_before
        logger.info(f"💵 Step 2 (Convert): USD balance before = ${usd_before:.4f}")

        records = self._convert_dust(dust_positions)
        result.records = records
        result.dust_converted = sum(1 for r in records if r.success)
        result.dust_failed = sum(1 for r in records if not r.success)

        logger.info(
            f"   Converted: {result.dust_converted} | Failed: {result.dust_failed}"
        )

        # ── Step 3: Verify ────────────────────────────────────────────
        verification_passed, usd_after, usd_recovered = self._verify(
            usd_before, result.dust_converted
        )
        result.usd_balance_after = usd_after
        result.usd_recovered = usd_recovered
        result.verification_passed = verification_passed

        if result.dust_failed > 0 and result.dust_converted == 0:
            # All conversions failed – no USD was recovered; dust still exists
            result.verification_passed = False
            result.error = "conversion failed: no dust positions could be sold"
            self._log_summary(result)
            return result

        if not verification_passed and result.dust_converted > 0:
            logger.error(
                "❌ Step 3 (Verify): USD balance did not increase after conversion"
            )
            result.error = "verification failed: USD balance did not increase"
            self._log_summary(result)
            return result

        logger.info(
            f"✅ Step 3 (Verify): USD recovered = ${usd_recovered:.4f} "
            f"(${usd_before:.4f} → ${usd_after:.4f})"
        )

        result.success = result.dust_failed == 0

        # ── Step 4: Resume ────────────────────────────────────────────
        result = self._maybe_resume_trading(result, reason="dust cleared and verified")

        self._log_summary(result)
        return result

    # ------------------------------------------------------------------
    # Step 1 – Identify
    # ------------------------------------------------------------------

    def _identify_dust(self) -> List[DustPosition]:
        """Return every broker position whose USD value is below the threshold."""
        dust: List[DustPosition] = []

        try:
            positions = self.broker.get_positions()
        except Exception as exc:
            logger.error(f"❌ Identify: could not fetch positions: {exc}")
            return dust

        if not positions:
            return dust

        for pos in positions:
            symbol = pos.get("symbol", "UNKNOWN")
            quantity = float(pos.get("quantity", 0.0))

            # Use pre-computed USD value if available
            usd_value = float(pos.get("usd_value", pos.get("size_usd", 0.0)))
            if usd_value <= 0.0:
                try:
                    price = self.broker.get_current_price(symbol)
                    usd_value = quantity * price if price and price > 0 else 0.0
                except Exception:
                    usd_value = 0.0

            if usd_value < self.dust_threshold_usd:
                currency = pos.get(
                    "currency", symbol.split("-")[0] if "-" in symbol else symbol
                )
                dust.append(
                    DustPosition(
                        symbol=symbol,
                        quantity=quantity,
                        usd_value=usd_value,
                        currency=currency,
                    )
                )
                logger.info(
                    f"   🗑️  DUST: {symbol} qty={quantity:.8f}  "
                    f"value=${usd_value:.4f}"
                )

        return dust

    # ------------------------------------------------------------------
    # Step 2 – Convert
    # ------------------------------------------------------------------

    def _convert_dust(self, dust_positions: List[DustPosition]) -> List[ConversionRecord]:
        """Sell every dust position to USD and return audit records."""
        records: List[ConversionRecord] = []

        for dp in dust_positions:
            ts = datetime.utcnow().isoformat()

            if self.dry_run:
                msg = f"DRY-RUN: would sell {dp.quantity:.8f} {dp.symbol} (${dp.usd_value:.4f})"
                logger.info(f"   [DRY-RUN] {msg}")
                records.append(
                    ConversionRecord(
                        timestamp=ts,
                        symbol=dp.symbol,
                        quantity=dp.quantity,
                        usd_value=dp.usd_value,
                        success=True,
                        message=msg,
                    )
                )
                continue

            success, msg = self._sell_position(dp)
            records.append(
                ConversionRecord(
                    timestamp=ts,
                    symbol=dp.symbol,
                    quantity=dp.quantity,
                    usd_value=dp.usd_value,
                    success=success,
                    message=msg,
                )
            )

            if success:
                logger.info(f"   ✅ Converted {dp.symbol}: ${dp.usd_value:.4f} → USD")
            else:
                logger.error(f"   ❌ Failed to convert {dp.symbol}: {msg}")

        return records

    def _sell_position(self, dp: DustPosition) -> Tuple[bool, str]:
        """
        Place a market sell order to liquidate *dp*.

        Tries broker methods in this order:
          1. ``broker.close_position(symbol)``
          2. ``broker.place_order(symbol, 'sell', 'market', size)``
          3. ``broker.place_market_order(symbol, side, quantity, ...)``

        Returns ``(success, message)``.
        """
        broker = self.broker

        # Method 1: close_position
        if hasattr(broker, "close_position"):
            try:
                result = broker.close_position(dp.symbol)
                if result and result.get("status") not in ("error", "failed"):
                    return True, f"close_position succeeded (status={result.get('status')})"
                return False, f"close_position returned error: {result}"
            except Exception as exc:
                logger.debug(f"      close_position raised: {exc}")

        # Method 2: place_order
        if hasattr(broker, "place_order"):
            try:
                result = broker.place_order(
                    symbol=dp.symbol,
                    side="sell",
                    order_type="market",
                    size=dp.quantity,
                )
                if result and result.get("status") not in ("error", "failed"):
                    return True, f"place_order succeeded (status={result.get('status')})"
                return False, f"place_order returned error: {result}"
            except Exception as exc:
                return False, f"place_order raised: {exc}"

        # Method 3: place_market_order (Coinbase-style)
        if hasattr(broker, "place_market_order"):
            try:
                result = broker.place_market_order(
                    symbol=dp.symbol,
                    side="sell",
                    quantity=dp.quantity,
                    size_type="base",
                    force_liquidate=True,
                    ignore_min_trade=True,
                )
                if result and result.get("status") in ("filled", "completed", "success"):
                    return True, f"place_market_order succeeded (status={result.get('status')})"
                return False, f"place_market_order returned error: {result}"
            except Exception as exc:
                return False, f"place_market_order raised: {exc}"

        return False, "Broker has no supported sell method"

    # ------------------------------------------------------------------
    # Step 3 – Verify
    # ------------------------------------------------------------------

    def _verify(
        self,
        usd_before: float,
        conversions_attempted: int,
    ) -> Tuple[bool, float, float]:
        """
        Confirm that the USD cash balance increased after conversion.

        In dry-run mode the balance check is skipped and verification is
        always reported as passed (since no real orders were placed).

        Returns:
            Tuple of (passed, usd_after, usd_recovered).
        """
        if self.dry_run:
            logger.info("   [DRY-RUN] Verify step skipped (no real balance change)")
            return True, usd_before, 0.0

        if conversions_attempted == 0:
            # Nothing was converted; verification passes trivially
            return True, usd_before, 0.0

        usd_after = self._get_usd_balance()
        usd_recovered = max(0.0, usd_after - usd_before)
        passed = usd_after > usd_before

        return passed, usd_after, usd_recovered

    # ------------------------------------------------------------------
    # Step 4 – Resume
    # ------------------------------------------------------------------

    def _maybe_resume_trading(self, result: PipelineResult, reason: str) -> PipelineResult:
        """
        Re-enable trading via the RecoveryController (if one was provided).

        If no controller was supplied this step is a no-op.
        """
        if self.recovery_controller is None:
            logger.info("   ℹ️  Resume step skipped (no RecoveryController provided)")
            return result

        try:
            enabled = self.recovery_controller.enable_trading(
                reason=f"Dust-to-USD pipeline: {reason}"
            )
            result.trading_resumed = bool(enabled)
            if enabled:
                logger.info("✅ Step 4 (Resume): Trading re-enabled via RecoveryController")
            else:
                logger.warning(
                    "⚠️  Step 4 (Resume): RecoveryController did not enable trading "
                    "(may require manual state transition first)"
                )
        except Exception as exc:
            logger.error(f"❌ Step 4 (Resume): enable_trading raised: {exc}")

        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_usd_balance(self) -> float:
        """Fetch the current USD cash balance from the broker."""
        try:
            if hasattr(self.broker, "get_usd_balance"):
                return float(self.broker.get_usd_balance())
            # Fallback: try generic balance methods
            if hasattr(self.broker, "get_balance"):
                bal = self.broker.get_balance()
                if isinstance(bal, dict):
                    return float(bal.get("USD", bal.get("usd", 0.0)))
                return float(bal)
        except Exception as exc:
            logger.warning(f"   ⚠️  Could not fetch USD balance: {exc}")
        return 0.0

    def _log_summary(self, result: PipelineResult) -> None:
        """Print a human-readable pipeline summary."""
        logger.info("=" * 70)
        logger.info("💰 DUST-TO-USD PIPELINE COMPLETE")
        logger.info("=" * 70)
        logger.info(f"   Overall success    : {'✅ YES' if result.success else '❌ NO'}")
        logger.info(f"   Dust identified    : {result.dust_identified}")
        logger.info(f"   Converted to USD   : {result.dust_converted}")
        logger.info(f"   Failed conversions : {result.dust_failed}")
        if not self.dry_run:
            logger.info(f"   USD before         : ${result.usd_balance_before:.4f}")
            logger.info(f"   USD after          : ${result.usd_balance_after:.4f}")
            logger.info(f"   USD recovered      : ${result.usd_recovered:.4f}")
        logger.info(f"   Verification passed: {'✅ YES' if result.verification_passed else '❌ NO'}")
        logger.info(f"   Trading resumed    : {'✅ YES' if result.trading_resumed else 'N/A'}")
        if result.error:
            logger.error(f"   Error              : {result.error}")
        logger.info("=" * 70)
