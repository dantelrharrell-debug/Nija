#!/usr/bin/env python3
"""
Position Cap Enforcer - Auto-reduce holdings to maximum allowed count

Ensures open position count never exceeds the cap.
Automatically sells lowest-momentum or most-exposed positions.
Runs before market entry to keep leverage under control.
"""

import os
import sys
import logging
from typing import List, Dict, Tuple, Optional

# Setup logger
logger = logging.getLogger("nija.enforcer")

# Constants
# ✅ REQUIREMENT 3: DUST EXCLUSION - If usd_value < MIN_POSITION_USD, IGNORE COMPLETELY
DUST_THRESHOLD_USD = 1.00  # USD value threshold for dust positions (consistent with broker)
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
    BLACKLIST_THRESHOLD = DUST_THRESHOLD_USD


class PositionCapEnforcer:
    """
    Enforces maximum open position count by auto-liquidating excess positions.

    Safe, deterministic approach:
    - Reads current Coinbase holdings
    - Ranks by momentum (oversold/weak) or unrealized loss
    - Sells positions in order until count <= max_allowed
    """

    def __init__(self, max_positions: int = 8, broker: Optional[CoinbaseBroker] = None):
        """
        Initialize position cap enforcer.

        Args:
            max_positions: Maximum allowed open positions (default: 8 - consistent across all configs)
            broker: CoinbaseBroker instance (created if None)
        """
        self.max_positions = max_positions
        self.broker = broker or CoinbaseBroker()
        
        # Initialize dust blacklist for permanent sub-$1 position exclusion
        self.dust_blacklist = get_dust_blacklist() if get_dust_blacklist else None
        
        logger.info(f"PositionCapEnforcer initialized: max={max_positions} positions")
        if self.dust_blacklist:
            stats = self.dust_blacklist.get_stats()
            logger.info(f"  Dust blacklist loaded: {stats['count']} symbols (threshold: ${stats['threshold_usd']:.2f})")

    def get_current_positions(self) -> List[Dict]:
        """
        Fetch current crypto holdings from broker, filtering out:
        - Blacklisted symbols (permanently excluded dust positions)
        - New dust positions (< $1 USD value) which get added to blacklist
        
        Returns:
            List of position dicts: {'symbol', 'currency', 'balance', 'price', 'usd_value'}
        """
        try:
            if not self.broker.connect():
                logger.error("Failed to connect to broker")
                return []

            # Use broker's get_positions() method which works for all brokers
            positions = self.broker.get_positions()

            result = []
            dust_count = 0
            blacklisted_count = 0
            
            for pos in positions:
                symbol = pos.get('symbol', '')
                currency = pos.get('currency', symbol.split('-')[0] if '-' in symbol else symbol)
                balance = float(pos.get('quantity', 0))

                if balance <= 0:
                    continue
                
                # Check permanent blacklist first
                if self.dust_blacklist and self.dust_blacklist.is_blacklisted(symbol):
                    blacklisted_count += 1
                    logger.debug(f"⛔ Skipping blacklisted symbol: {symbol}")
                    continue

                # Try to get current price
                try:
                    price = self.broker.get_current_price(symbol)

                    # CRITICAL FIX: Add None-check safety guard
                    # Prevents counting positions with invalid price fetches
                    if price is None:
                        logger.error(f"❌ Price fetch failed for {symbol} — symbol mismatch")
                        logger.error(f"   💡 This position cannot be valued due to incorrect broker symbol format")
                        # CRITICAL: Still count position even if price fetch fails (use fallback price)
                        # This prevents ghost positions from being invisible
                        price = 1.0  # Fallback for counting purposes
                        logger.warning(f"   Using fallback price $1.00 for counting position")
                    elif price <= 0:
                        price = 1.0  # Fallback if price unavailable

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
                    logger.warning(f"Could not fetch price for {symbol}: {e}")
                    # CRITICAL: Still count position even if price fetch fails (use fallback price)
                    # This prevents rate limiting from causing undercounting
                    usd_value = balance * 1.0  # Conservative $1 estimate
                    if balance > 0.001:  # Only skip true dust
                        logger.warning(f"⚠️ RATE LIMITED: Counting {symbol} with fallback price (balance={balance})")
                        result.append({
                            'symbol': symbol,
                            'currency': currency,
                            'balance': balance,
                            'price': 1.0,  # Fallback
                            'usd_value': usd_value
                        })
            
            # Log summary
            if dust_count > 0 or blacklisted_count > 0:
                logger.info(f"📊 Position filtering summary:")
                logger.info(f"   Valid positions: {len(result)}")
                logger.info(f"   Dust positions found: {dust_count}")
                logger.info(f"   Blacklisted positions skipped: {blacklisted_count}")

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
        # Sort by LARGEST first, then reverse to get smallest-to-liquidate first
        # This ensures we KEEP the top N largest positions
        ranked_largest_first = sorted(positions, key=lambda p: p['usd_value'], reverse=True)
        
        # Reverse to get smallest positions first (these will be liquidated)
        ranked = list(reversed(ranked_largest_first))

        logger.info(f"Ranked {len(ranked)} positions for liquidation:")
        logger.info(f"  📊 KEEPING largest positions, selling smallest:")
        for i, pos in enumerate(ranked, 1):
            logger.info(f"  {i}. {pos['symbol']}: ${pos['usd_value']:.2f} ← LIQUIDATE")
        
        logger.info(f"  📌 Positions to KEEP (largest {self.max_positions}):")
        for i, pos in enumerate(ranked_largest_first[:self.max_positions], 1):
            logger.info(f"  {i}. {pos['symbol']}: ${pos['usd_value']:.2f} ← KEEP")

        return ranked

    def sell_position(self, position: Dict) -> bool:
        """
        Market-sell a single position using broker.place_market_order.

        Args:
            position: Position dict with 'symbol', 'balance', etc.

        Returns:
            True if successful, False otherwise
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
                logger.info(f"✅ SOLD {currency}! Order placed.")
                return True
            else:
                error = result.get('error') if result else 'Unknown'
                logger.error(f"❌ Sell failed for {currency}: {error}")
                return False

        except Exception as e:
            logger.error(f"❌ Error selling {symbol}: {e}")
            return False

    def enforce_cap(self) -> Tuple[bool, Dict]:
        """
        Enforce position cap by auto-selling excess positions.
        
        Strategy:
        1. Sort positions by USD value (largest first)
        2. Keep top N positions (largest holdings)
        3. Liquidate remaining positions (smallest holdings)
        4. Block new entries until normalized

        Returns:
            (success: bool, result_dict with counts and actions)
        """
        logger.info(f"🔍 ENFORCE: Checking position cap (max={self.max_positions})...")

        positions = self.get_current_positions()
        current_count = len(positions)

        logger.info(f"   Current positions: {current_count} (after blacklist filtering)")

        if current_count <= self.max_positions:
            logger.info(f"✅ Under cap (no action needed)")
            return True, {
                'current_count': current_count,
                'max_allowed': self.max_positions,
                'excess': 0,
                'sold': 0,
                'status': 'compliant'
            }

        # Over cap: liquidate excess
        excess = current_count - self.max_positions
        logger.warning(f"🚨 OVER CAP by {excess} positions! Auto-liquidating...")
        logger.warning(f"   Strategy: KEEP {self.max_positions} largest, SELL {excess} smallest")

        ranked = self.rank_positions_for_liquidation(positions)
        sold_count = 0

        for i, pos in enumerate(ranked[:excess]):
            logger.info(f"\nSelling position {i+1}/{excess}...")
            if self.sell_position(pos):
                sold_count += 1
                import time
                time.sleep(1)  # Rate-limit API calls

        logger.info(f"\n" + "="*70)
        logger.info(f"ENFORCER SUMMARY: Sold {sold_count}/{excess} excess positions")
        logger.info(f"="*70)

        return sold_count == excess, {
            'current_count': current_count,
            'max_allowed': self.max_positions,
            'excess': excess,
            'sold': sold_count,
            'status': 'enforced' if sold_count == excess else 'partial'
        }


def main():
    """Run position cap enforcer as standalone script."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(name)s | %(levelname)s | %(message)s'
    )

    enforcer = PositionCapEnforcer(max_positions=8)
    success, result = enforcer.enforce_cap()

    if success:
        logger.info(f"✅ Position cap enforced successfully")
    else:
        logger.warning(f"⚠️ Partial enforcement: {result['sold']}/{result['excess']} sold")

    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
