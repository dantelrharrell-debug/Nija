#!/usr/bin/env python3
"""
Position Cap Enforcer - Auto-reduce holdings to maximum allowed count

Ensures open position count never exceeds the cap.
Automatically sells lowest-momentum or most-exposed positions.
Runs before market entry to keep leverage under control.
"""

import os
import sys
import time
import logging
from typing import List, Dict, Tuple, Optional

# Setup logger
logger = logging.getLogger("nija.enforcer")

# Constants
# ✅ REQUIREMENT 3: DUST EXCLUSION - If usd_value < MIN_POSITION_USD, IGNORE COMPLETELY
DUST_THRESHOLD_USD = 2.00  # USD value threshold for dust positions (raised from $1 to $2)
MIN_POSITION_USD = DUST_THRESHOLD_USD  # Alias for clarity - positions below this are ignored

# Add bot dir to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

try:
    from broker_manager import CoinbaseBroker
except ImportError:
    logger.error("Failed to import broker_manager")
    CoinbaseBroker = None

try:
    from dust_blacklist import get_dust_blacklist, DUST_THRESHOLD_USD as BLACKLIST_THRESHOLD
except ImportError:
    logger.warning("Failed to import dust_blacklist - blacklist feature disabled")
    get_dust_blacklist = None
    BLACKLIST_THRESHOLD = 1.00  # Fallback value when dust_blacklist is not available


class PositionCapEnforcer:
    """
    Enforces maximum open position count by auto-liquidating excess positions.

    Safe, deterministic approach:
    - Reads current Coinbase holdings
    - Ranks by momentum (oversold/weak) or unrealized loss
    - Sells positions in order until count <= max_allowed
    """

    # How long (seconds) a failed-sell symbol stays in the unsellable set
    # before being retried.  Mirrors UNSELLABLE_RETRY_HOURS in trading_strategy.py.
    UNSELLABLE_RETRY_SECONDS = 12 * 3600  # 12 hours

    def __init__(self, max_positions: int = 5, broker: Optional[CoinbaseBroker] = None):
        """
        Initialize position cap enforcer.

        Args:
            max_positions: Maximum allowed open positions (default: 5 - global hard cap)
            broker: CoinbaseBroker instance (created if None)
        """
        self.max_positions = max_positions
        self.broker = broker or CoinbaseBroker()

        # Track positions that cannot be sold (below min size, API errors, etc.)
        # Maps symbol -> timestamp when it was first marked unsellable.
        # Unsellable positions are excluded from the cap count so they don't
        # permanently block new entries.
        self._unsellable_positions: Dict[str, float] = {}

        # Initialize dust blacklist for permanent sub-$1 position exclusion
        self.dust_blacklist = get_dust_blacklist() if get_dust_blacklist else None
        
        logger.info(f"PositionCapEnforcer initialized: max={max_positions} positions")
        if self.dust_blacklist:
            stats = self.dust_blacklist.get_stats()
            logger.info(f"  Dust blacklist loaded: {stats['count']} symbols (threshold: ${stats['threshold_usd']:.2f})")

    def get_current_positions(self) -> List[Dict]:
        """
        Fetch current crypto holdings from broker, filtering out:
        - Symbols in the timed unsellable set (failed-sell retry window active)
        - Blacklisted symbols (permanently excluded dust positions)
        - New dust positions (< $1 USD value) which get added to blacklist
        
        Returns:
            List of position dicts: {'symbol', 'currency', 'balance', 'price', 'usd_value'}
        """
        # Expire stale unsellable entries before filtering
        _now = time.time()
        expired = [
            sym for sym, ts in list(self._unsellable_positions.items())
            if _now - ts >= self.UNSELLABLE_RETRY_SECONDS
        ]
        for sym in expired:
            del self._unsellable_positions[sym]
            logger.info(f"🔄 {sym}: unsellable retry window expired — will attempt sell again")

        try:
            if not self.broker.connect():
                logger.error("Failed to connect to broker")
                return []

            # Use broker's get_positions() method which works for all brokers
            positions = self.broker.get_positions()

            result = []
            dust_count = 0
            blacklisted_count = 0
            unsellable_count = 0

            for pos in positions:
                symbol = pos.get('symbol', '')
                currency = pos.get('currency', symbol.split('-')[0] if '-' in symbol else symbol)
                balance = float(pos.get('quantity', 0))

                if balance <= 0:
                    continue

                # Exclude symbols inside the unsellable retry window
                if symbol in self._unsellable_positions:
                    unsellable_count += 1
                    elapsed_h = (_now - self._unsellable_positions[symbol]) / 3600
                    logger.debug(
                        f"   ⏭️ Excluding {symbol} from cap count "
                        f"(marked unsellable {elapsed_h:.1f}h ago)"
                    )
                    continue

                # Check permanent blacklist
                if self.dust_blacklist and self.dust_blacklist.is_blacklisted(symbol):
                    blacklisted_count += 1
                    logger.debug(f"⛔ Skipping blacklisted symbol: {symbol}")
                    continue

                # Try to get current price
                try:
                    price = self.broker.get_current_price(symbol)

                    # CRITICAL FIX: Block valuation if price fetch fails
                    # Institutional systems NEVER use arbitrary fallback prices
                    if price is None or price <= 0:
                        logger.error(f"❌ CRITICAL: Cannot value position {symbol} — price fetch failed")
                        logger.error(f"   💡 Trading PAUSED for this symbol until price available")
                        logger.error(f"   💡 Position exists but cannot be valued - BLOCKING VALUATION")
                        # CRITICAL: Do NOT count positions we cannot value
                        # This prevents trading on fake data
                        continue

                    usd_value = balance * price

                    # PERMANENT BLACKLIST: Add dust positions to blacklist
                    if usd_value < DUST_THRESHOLD_USD:
                        dust_count += 1
                        logger.info(f"🗑️  Found dust position {symbol}: ${usd_value:.4f} (below ${DUST_THRESHOLD_USD} threshold)")
                        
                        # Add to permanent blacklist
                        if self.dust_blacklist:
                            self.dust_blacklist.add_to_blacklist(
                                symbol=symbol,
                                usd_value=usd_value,
                                reason=f"dust position (${usd_value:.4f} < ${DUST_THRESHOLD_USD})"
                            )
                        continue

                    result.append({
                        'symbol': symbol,
                        'currency': currency,
                        'balance': balance,
                        'price': price,
                        'usd_value': usd_value
                    })
                except Exception as e:
                    # CRITICAL: Block valuation if price fetch fails
                    # Never use arbitrary fallback prices
                    logger.error(f"❌ CRITICAL: Cannot value position {symbol}: {e}")
                    logger.error(f"   💡 Trading PAUSED for this symbol until price available")
                    logger.error(f"   💡 Position exists but cannot be valued - BLOCKING VALUATION")
                    # Do NOT count positions we cannot value
                    continue
            
            # Log summary
            if dust_count > 0 or blacklisted_count > 0 or unsellable_count > 0:
                logger.info(f"📊 Position filtering summary:")
                logger.info(f"   Valid positions: {len(result)}")
                if dust_count:
                    logger.info(f"   Dust positions found: {dust_count}")
                if blacklisted_count:
                    logger.info(f"   Blacklisted positions skipped: {blacklisted_count}")
                if unsellable_count:
                    logger.info(f"   Unsellable positions excluded: {unsellable_count}")

            return result
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return []

    def rank_positions_for_liquidation(self, positions: List[Dict]) -> List[Dict]:
        """
        Rank positions by priority for liquidation.

        Strategy: Keep LARGEST positions by USD value, liquidate smallest.
        This ensures we maintain exposure to our best/largest holdings.

        Args:
            positions: List of position dicts

        Returns:
            Ranked list (highest-priority-to-sell first = smallest positions)
        """
        # Sort by smallest first (these will be liquidated)
        # This is more efficient than sorting by largest then reversing
        ranked_smallest_first = sorted(positions, key=lambda p: p['usd_value'])
        
        # Also create largest-first list for logging which positions we keep
        ranked_largest_first = sorted(positions, key=lambda p: p['usd_value'], reverse=True)

        logger.info(f"Ranked {len(ranked_smallest_first)} positions for liquidation:")
        logger.info(f"  📊 KEEPING largest positions, selling smallest:")
        for i, pos in enumerate(ranked_smallest_first, 1):
            logger.info(f"  {i}. {pos['symbol']}: ${pos['usd_value']:.2f} (LIQUIDATE)")
        
        logger.info(f"  📌 Positions to KEEP (largest {self.max_positions}):")
        for i, pos in enumerate(ranked_largest_first[:self.max_positions], 1):
            logger.info(f"  {i}. {pos['symbol']}: ${pos['usd_value']:.2f} (KEEP)")

        return ranked_smallest_first

    def sell_position(self, position: Dict) -> bool:
        """
        Market-sell a single position using broker.place_market_order.

        Args:
            position: Position dict with 'symbol', 'balance', etc.

        Returns:
            True if successful, False otherwise

        Side-effect:
            On a confirmed "unsellable" failure (order below exchange minimum)
            the symbol is added to ``_unsellable_positions`` so that subsequent
            cap-count checks exclude it for ``UNSELLABLE_RETRY_SECONDS``.
        """
        symbol = position['symbol']
        balance = position['balance']
        currency = position['currency']

        try:
            logger.info(f"🔴 ENFORCER: Selling {currency}... (${position['usd_value']:.2f})")

            # CRITICAL FIX: Use correct parameter names (quantity, not size) and size_type='base'
            result = self.broker.place_market_order(
                symbol=symbol,
                side='sell',
                quantity=balance,
                size_type='base'
            )

            if result and result.get('status') == 'filled':
                # Successful sell — clear any stale unsellable entry
                self._unsellable_positions.pop(symbol, None)
                logger.info(f"✅ SOLD {currency}! Order placed.")
                return True
            else:
                error = result.get('error') if result else 'Unknown'
                logger.error(f"❌ Sell failed for {currency}: {error}")
                # Mark as unsellable so it doesn't count toward cap during retry window
                if symbol not in self._unsellable_positions:
                    self._unsellable_positions[symbol] = time.time()
                    logger.info(
                        f"   ⏳ {symbol} marked unsellable for "
                        f"{self.UNSELLABLE_RETRY_SECONDS / 3600:.0f}h retry window"
                    )
                return False

        except Exception as e:
            logger.error(f"❌ Error selling {symbol}: {e}")
            # Mark as unsellable on exception too
            if symbol not in self._unsellable_positions:
                self._unsellable_positions[symbol] = time.time()
            return False

    def enforce_cap(self) -> Tuple[bool, Dict]:
        """
        Enforce position cap by auto-selling excess positions.
        
        CRITICAL INSTITUTIONAL-GRADE ENFORCEMENT:
        1. Fetch current positions
        2. If over cap, liquidate excess
        3. RE-FETCH positions to verify closure
        4. RE-RUN until compliant
        5. HALT TRADING if not compliant after max attempts
        
        Returns:
            (success: bool, result_dict with counts and actions)
        """
        logger.info(f"🔍 ENFORCE: Checking position cap (max={self.max_positions})...")
        
        max_enforcement_cycles = 3  # Maximum re-enforcement attempts
        
        for cycle in range(1, max_enforcement_cycles + 1):
            logger.info(f"\n{'='*70}")
            logger.info(f"ENFORCEMENT CYCLE {cycle}/{max_enforcement_cycles}")
            logger.info(f"{'='*70}")
            
            positions = self.get_current_positions()
            current_count = len(positions)

            logger.info(f"   Current positions: {current_count} (after blacklist filtering)")

            if current_count <= self.max_positions:
                logger.info(f"✅ COMPLIANT: {current_count}/{self.max_positions} positions (under cap)")
                return True, {
                    'current_count': current_count,
                    'max_allowed': self.max_positions,
                    'excess': 0,
                    'sold': 0,
                    'status': 'compliant',
                    'cycles': cycle
                }

            # Over cap: liquidate excess
            excess = current_count - self.max_positions
            logger.warning(f"🚨 VIOLATION: {excess} positions over cap! Auto-liquidating...")
            logger.warning(f"   Strategy: KEEP {self.max_positions} largest, SELL {excess} smallest")

            ranked = self.rank_positions_for_liquidation(positions)
            sold_count = 0

            for i, pos in enumerate(ranked[:excess]):
                logger.info(f"\nLiquidating position {i+1}/{excess}...")
                if self.sell_position(pos):
                    sold_count += 1
                    import time
                    time.sleep(1)  # Rate-limit API calls
                else:
                    logger.error(f"❌ Failed to liquidate {pos['symbol']} — enforcement incomplete")

            logger.info(f"\n{'='*70}")
            logger.info(f"CYCLE {cycle} SUMMARY: Liquidated {sold_count}/{excess} positions")
            logger.info(f"{'='*70}")
            
            # CRITICAL: Wait for orders to settle before re-checking
            logger.info(f"⏳ Waiting 3s for orders to settle...")
            import time
            time.sleep(3)
            
            # RE-FETCH positions to verify compliance
            logger.info(f"🔄 RE-FETCHING positions to verify compliance...")
            
        # If we reach here, enforcement failed after max cycles
        positions = self.get_current_positions()
        final_count = len(positions)
        
        logger.error(f"\n{'='*70}")
        logger.error(f"🚨 CRITICAL FAILURE: Position cap enforcement FAILED")
        logger.error(f"   Initial positions: {current_count}")
        logger.error(f"   Final positions: {final_count}")
        logger.error(f"   Max allowed: {self.max_positions}")
        logger.error(f"   Cycles attempted: {max_enforcement_cycles}")
        logger.error(f"{'='*70}")
        logger.error(f"🛑 TRADING HALTED until manual intervention")
        
        return False, {
            'current_count': final_count,
            'max_allowed': self.max_positions,
            'excess': final_count - self.max_positions if final_count > self.max_positions else 0,
            'sold': sold_count,
            'status': 'failed_enforcement',
            'cycles': max_enforcement_cycles,
            'trading_halted': True
        }


def main():
    """Run position cap enforcer as standalone script."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(name)s | %(levelname)s | %(message)s'
    )

    enforcer = PositionCapEnforcer(max_positions=5)
    success, result = enforcer.enforce_cap()

    if success:
        logger.info(f"✅ Position cap enforced successfully")
    else:
        logger.warning(f"⚠️ Partial enforcement: {result['sold']}/{result['excess']} sold")

    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
