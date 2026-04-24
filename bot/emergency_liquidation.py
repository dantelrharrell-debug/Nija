#!/usr/bin/env python3
"""
Emergency Liquidation Module
Forces immediate liquidation of positions with losses >= -1% to protect capital
"""

import logging
from typing import Dict

logger = logging.getLogger("nija.emergency")


class EmergencyLiquidator:
    """
    Emergency liquidation system for capital preservation.

    Forces immediate position closure when PnL reaches -1% threshold,
    bypassing all normal trading checks and filters.
    """

    def __init__(self, threshold_pct: float = -0.01):
        """
        Initialize emergency liquidator.

        Args:
            threshold_pct: PnL threshold for forced liquidation (default: -1% = -0.01)
        """
        self.threshold_pct = threshold_pct
        logger.debug(f"🚨 Emergency Liquidator initialized: threshold={threshold_pct*100:.1f}%")

    def should_force_liquidate(self, position: Dict, current_price: float) -> bool:
        """
        Check if position should be force-liquidated based on PnL.

        Args:
            position: Position dict with 'entry_price', 'size_usd', and 'side'
            current_price: Current market price

        Returns:
            True if position loss >= threshold (e.g., -1%), False otherwise
        """
        try:
            entry_price = position.get('entry_price')
            side = position.get('side', 'long')

            if entry_price is None or entry_price == 0:
                logger.warning("Cannot calculate PnL: missing or zero entry price")
                return False

            # Calculate PnL percentage
            if side == 'long':
                pnl_pct = (current_price - entry_price) / entry_price
            else:  # short
                pnl_pct = (entry_price - current_price) / entry_price

            # Check if loss exceeds threshold
            if pnl_pct <= self.threshold_pct:
                symbol = position.get('symbol', 'UNKNOWN')
                logger.warning(
                    f"🚨 EMERGENCY LIQUIDATION TRIGGERED: {symbol} "
                    f"PnL={pnl_pct*100:.2f}% (threshold={self.threshold_pct*100:.1f}%)"
                )
                return True

            return False

        except Exception as e:
            logger.error(f"Error checking emergency liquidation: {e}")
            return False
