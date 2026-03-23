"""
AUTO DUST SWEEPER
=================
Enhanced dust sweeper that converts all sub-threshold positions into a single
configurable target asset (e.g. BTC-USD, ETH-USD) rather than leaving them as
USDT fragments.

Why "one asset" consolidation beats plain USDT conversion
----------------------------------------------------------
* Keeps capital deployed in a single high-conviction hold instead of idle cash.
* Reduces the position count which lowers portfolio complexity and fee drag.
* Allows the bot to benefit from upside on the chosen consolidation asset.

Pipeline (called once per cleanup cycle):
  1. **Scan** – identify all positions below ``dust_threshold_usd``.
  2. **Sort** – order dust positions by PnL% ascending (sell worst-losers first).
  3. **Sell each dust position** – market-sell into quote currency (USDT/USD).
  4. **Re-buy target asset** – once all dust is sold, aggregate the proceeds and
     buy a single position in ``target_asset``.
  5. **Report** – return a structured ``DustSweepResult`` for audit/logging.

Usage
-----
    from bot.auto_dust_sweeper import get_auto_dust_sweeper
    result = get_auto_dust_sweeper(target_asset="BTC-USD").sweep(
        broker, positions, portfolio_value_usd=5000.0
    )

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nija.auto_dust_sweeper")

# ---------------------------------------------------------------------------
# Default configuration constants
# ---------------------------------------------------------------------------

DEFAULT_DUST_THRESHOLD_USD: float = 3.0    # Positions below $3 are swept
DEFAULT_TARGET_ASSET: str = "BTC-USD"       # Default consolidation asset
MIN_REBUY_USD: float = 5.0                  # Minimum aggregated proceeds to trigger re-buy


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class DustSweepAction:
    """Record for one sell action during a dust sweep."""
    symbol: str
    size_usd: float
    quantity: float
    pnl_pct: float
    action: str          # "SOLD" | "SKIP" | "ERROR"
    success: bool
    message: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class DustSweepResult:
    """Full result returned by AutoDustSweeper.sweep()."""
    run_timestamp: str
    target_asset: str
    positions_scanned: int
    dust_found: int
    dust_sold: int
    dust_skipped: int
    proceeds_usd: float              # Total USD recovered from dust sales
    rebuy_attempted: bool
    rebuy_success: bool
    rebuy_usd: float                 # Amount re-invested in target_asset
    actions: List[DustSweepAction] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"AutoDustSweeper: scanned={self.positions_scanned} "
            f"dust={self.dust_found} sold={self.dust_sold} "
            f"skipped={self.dust_skipped} proceeds=${self.proceeds_usd:.4f} "
            f"rebuy={'✅' if self.rebuy_success else '❌'} "
            f"→{self.target_asset} ${self.rebuy_usd:.4f}"
        )


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------

class AutoDustSweeper:
    """
    Convert all dust positions into a single configurable target asset.

    Parameters
    ----------
    dust_threshold_usd:
        Positions (USD value) below this threshold are treated as dust.
    target_asset:
        The symbol to re-buy with the aggregated dust proceeds
        (e.g. ``"BTC-USD"``, ``"ETH-USD"``).
    dry_run:
        When ``True``, logs all planned actions but makes no broker calls.
    min_rebuy_usd:
        Minimum aggregated proceeds required before attempting the re-buy.
        Prevents placing orders too small for exchange minimums.
    """

    def __init__(
        self,
        dust_threshold_usd: float = DEFAULT_DUST_THRESHOLD_USD,
        target_asset: str = DEFAULT_TARGET_ASSET,
        dry_run: bool = False,
        min_rebuy_usd: float = MIN_REBUY_USD,
    ) -> None:
        self.dust_threshold_usd = dust_threshold_usd
        self.target_asset = target_asset
        self.dry_run = dry_run
        self.min_rebuy_usd = min_rebuy_usd
        self._lock = threading.Lock()
        # Accumulated proceeds from sweeps where we sold dust but couldn't yet
        # reach min_rebuy_usd.  Persists across sweep cycles so that small
        # proceeds from multiple runs are combined before the re-buy fires.
        self._accumulated_proceeds: float = 0.0
        logger.info(
            "🧹 AutoDustSweeper initialised | dust<$%.2f | target=%s | dry_run=%s | min_rebuy=$%.2f",
            dust_threshold_usd, target_asset, dry_run, min_rebuy_usd,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def sweep(
        self,
        broker: Any,
        positions: List[Dict],
        portfolio_value_usd: float = 0.0,
    ) -> DustSweepResult:
        """
        Run the full dust-to-one-asset sweep.

        Parameters
        ----------
        broker:
            Live broker instance exposing ``place_market_order``.
        positions:
            Current open positions list.  Each entry needs at minimum:
            ``symbol``, ``size_usd`` (or ``usd_value``), ``quantity``
            (or ``base_size``).
        portfolio_value_usd:
            Total portfolio value (used for logging/context only).
        """
        with self._lock:
            return self._run(broker, positions, portfolio_value_usd)

    # ------------------------------------------------------------------
    # Internal implementation
    # ------------------------------------------------------------------

    def _run(
        self,
        broker: Any,
        positions: List[Dict],
        portfolio_value_usd: float,
    ) -> DustSweepResult:
        now_ts = datetime.now(timezone.utc).isoformat()
        result = DustSweepResult(
            run_timestamp=now_ts,
            target_asset=self.target_asset,
            positions_scanned=len(positions),
            dust_found=0,
            dust_sold=0,
            dust_skipped=0,
            proceeds_usd=0.0,
            rebuy_attempted=False,
            rebuy_success=False,
            rebuy_usd=0.0,
        )

        if not positions:
            logger.info("🧹 AutoDustSweeper: no positions to scan")
            return result

        logger.info(
            "🧹 AutoDustSweeper START | %d positions | portfolio=$%.2f | target=%s",
            len(positions), portfolio_value_usd, self.target_asset,
        )

        # Step 1 – identify dust positions (exclude the target asset itself)
        dust = [
            p for p in positions
            if p.get("symbol") != self.target_asset
            and 0 < self._size_usd(p) < self.dust_threshold_usd
        ]

        # Also include positions with zero USD value but non-zero quantity (stranded)
        for p in positions:
            if p.get("symbol") == self.target_asset:
                continue
            size = self._size_usd(p)
            qty = self._quantity(p)
            if size == 0 and qty > 0 and p not in dust:
                dust.append(p)

        result.dust_found = len(dust)

        if not dust:
            logger.info("🧹 AutoDustSweeper: no dust found")
            return result

        logger.warning(
            "🧹 AutoDustSweeper: %d dust position(s) below $%.2f",
            len(dust), self.dust_threshold_usd,
        )

        # Step 2 – sort by PnL% ascending (sell worst losers first)
        dust.sort(key=lambda p: float(p.get("pnl_pct") or 0))

        # Step 3 – sell each dust position
        for pos in dust:
            action = self._sell_dust(broker, pos)
            result.actions.append(action)
            if action.success:
                result.dust_sold += 1
                result.proceeds_usd += action.size_usd
            else:
                result.dust_skipped += 1
                if action.action == "ERROR":
                    result.errors.append(action.message)

        # Step 4 – re-buy target asset with aggregated proceeds
        # Accumulate proceeds across sweep cycles so that small amounts from
        # multiple runs combine before we attempt the re-buy.
        self._accumulated_proceeds += result.proceeds_usd
        total_available = self._accumulated_proceeds

        if total_available >= self.min_rebuy_usd:
            rebuy_action = self._buy_target(broker, total_available)
            result.rebuy_attempted = True
            result.rebuy_success = rebuy_action.success
            result.rebuy_usd = total_available if rebuy_action.success else 0.0
            result.actions.append(rebuy_action)
            if rebuy_action.success:
                # Reset accumulator after a successful re-buy
                self._accumulated_proceeds = 0.0
            else:
                result.errors.append(rebuy_action.message)
        else:
            logger.info(
                "🧹 AutoDustSweeper: accumulated $%.4f (need $%.2f for re-buy) — "
                "holding proceeds for next sweep cycle",
                total_available, self.min_rebuy_usd,
            )

        logger.info("🧹 AutoDustSweeper DONE | %s", result.summary())
        return result

    # ------------------------------------------------------------------
    # Execution helpers
    # ------------------------------------------------------------------

    def _sell_dust(self, broker: Any, position: Dict) -> DustSweepAction:
        """Market-sell one dust position and return an audit record."""
        symbol = position.get("symbol", "UNKNOWN")
        size_usd = self._size_usd(position)
        quantity = self._quantity(position)
        pnl_pct = float(position.get("pnl_pct") or 0)

        if quantity <= 0:
            msg = f"No quantity to sell for {symbol} (qty={quantity})"
            logger.warning("   ⚠️  %s", msg)
            return DustSweepAction(
                symbol=symbol, size_usd=size_usd, quantity=quantity,
                pnl_pct=pnl_pct, action="SKIP", success=False, message=msg,
            )

        if self.dry_run:
            msg = f"[DRY RUN] Would sell {symbol} qty={quantity:.8f} (${size_usd:.4f}, pnl={pnl_pct:+.2f}%)"
            logger.info("   %s", msg)
            return DustSweepAction(
                symbol=symbol, size_usd=size_usd, quantity=quantity,
                pnl_pct=pnl_pct, action="SOLD", success=True, message=msg,
            )

        try:
            logger.info(
                "   💱 Selling dust %s qty=%.8f ($%.4f, pnl=%+.2f%%)",
                symbol, quantity, size_usd, pnl_pct,
            )
            order = broker.place_market_order(
                symbol=symbol,
                side="sell",
                quantity=quantity,
                size_type="base",
            )
            filled = bool(
                order and order.get("status") in {"filled", "completed", "success"}
            )
            if filled:
                msg = f"Sold {symbol} qty={quantity:.8f} ${size_usd:.4f} | order={order.get('order_id', '?')}"
                logger.info("   ✅ %s", msg)
                return DustSweepAction(
                    symbol=symbol, size_usd=size_usd, quantity=quantity,
                    pnl_pct=pnl_pct, action="SOLD", success=True, message=msg,
                )
            else:
                msg = f"Order did not fill: {order}"
                logger.warning("   ⚠️  %s → %s", symbol, msg)
                return DustSweepAction(
                    symbol=symbol, size_usd=size_usd, quantity=quantity,
                    pnl_pct=pnl_pct, action="SKIP", success=False, message=msg,
                )
        except Exception as exc:
            msg = f"Exception selling {symbol}: {exc}"
            logger.error("   ❌ %s", msg)
            return DustSweepAction(
                symbol=symbol, size_usd=size_usd, quantity=quantity,
                pnl_pct=pnl_pct, action="ERROR", success=False, message=msg,
            )

    def _buy_target(self, broker: Any, amount_usd: float) -> DustSweepAction:
        """Buy ``self.target_asset`` with ``amount_usd`` of quote currency."""
        if self.dry_run:
            msg = f"[DRY RUN] Would buy ${amount_usd:.4f} of {self.target_asset}"
            logger.info("   %s", msg)
            return DustSweepAction(
                symbol=self.target_asset, size_usd=amount_usd, quantity=0.0,
                pnl_pct=0.0, action="BUY_TARGET", success=True, message=msg,
            )

        try:
            logger.info(
                "   🎯 Buying $%.4f of %s (consolidation)", amount_usd, self.target_asset
            )
            order = broker.place_market_order(
                symbol=self.target_asset,
                side="buy",
                quantity=amount_usd,
                size_type="quote",
            )
            filled = bool(
                order and order.get("status") in {"filled", "completed", "success"}
            )
            if filled:
                msg = (
                    f"Consolidated ${amount_usd:.4f} dust → {self.target_asset} "
                    f"| order={order.get('order_id', '?')}"
                )
                logger.info("   ✅ %s", msg)
                return DustSweepAction(
                    symbol=self.target_asset, size_usd=amount_usd, quantity=0.0,
                    pnl_pct=0.0, action="BUY_TARGET", success=True, message=msg,
                )
            else:
                msg = f"Re-buy into {self.target_asset} did not fill: {order}"
                logger.warning("   ⚠️  %s", msg)
                return DustSweepAction(
                    symbol=self.target_asset, size_usd=amount_usd, quantity=0.0,
                    pnl_pct=0.0, action="BUY_TARGET", success=False, message=msg,
                )
        except Exception as exc:
            msg = f"Exception buying {self.target_asset}: {exc}"
            logger.error("   ❌ %s", msg)
            return DustSweepAction(
                symbol=self.target_asset, size_usd=amount_usd, quantity=0.0,
                pnl_pct=0.0, action="BUY_TARGET", success=False, message=msg,
            )

    # ------------------------------------------------------------------
    # Field extractors
    # ------------------------------------------------------------------

    @staticmethod
    def _size_usd(position: Dict) -> float:
        return float(position.get("size_usd") or position.get("usd_value") or 0)

    @staticmethod
    def _quantity(position: Dict) -> float:
        return float(
            position.get("quantity")
            or position.get("base_size")
            or position.get("size")
            or position.get("balance")
            or 0
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_instance: Optional[AutoDustSweeper] = None
_instance_lock = threading.Lock()


def get_auto_dust_sweeper(
    dust_threshold_usd: float = DEFAULT_DUST_THRESHOLD_USD,
    target_asset: str = DEFAULT_TARGET_ASSET,
    dry_run: bool = False,
    min_rebuy_usd: float = MIN_REBUY_USD,
) -> AutoDustSweeper:
    """
    Return the process-wide AutoDustSweeper singleton.

    Configuration is applied only on the **first** call; subsequent calls
    return the existing instance unchanged.
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = AutoDustSweeper(
                    dust_threshold_usd=dust_threshold_usd,
                    target_asset=target_asset,
                    dry_run=dry_run,
                    min_rebuy_usd=min_rebuy_usd,
                )
    return _instance
