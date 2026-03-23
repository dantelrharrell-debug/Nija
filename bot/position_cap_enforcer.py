#!/usr/bin/env python3
"""
Position Cap Enforcer - Auto-reduce holdings to maximum allowed count

Ensures open position count never exceeds the cap.
Automatically sells lowest-momentum or most-exposed positions.
Runs before market entry to keep leverage under control.
"""

import logging
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

# CAP RESOLUTION ENGINE: unsellable positions are excluded from cap math for this
# many hours, then re-evaluated (the position value may have recovered enough to sell).
UNSELLABLE_DECAY_HOURS = 12.0

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

    PERFECT CLEANUP FLOW:
    - Single-pass enforcement (zero retry loops).
    - When a sell fails the position is marked *unsellable* for UNSELLABLE_DECAY_HOURS
      and excluded from the cap count until the decay window expires.

    CAP RESOLUTION ENGINE:
    - Only tradable positions count toward the cap.
    - Unsellable positions (below exchange minimum, API error, etc.) are silently
      excluded from cap math so they never permanently block new entries.
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
        # Maps symbol -> Unix timestamp when it was first marked unsellable.
        # Cleared automatically after UNSELLABLE_DECAY_HOURS so the position
        # gets a fresh attempt once the decay window expires.
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

    # ------------------------------------------------------------------
    # Unsellable-position helpers  (CAP RESOLUTION ENGINE)
    # ------------------------------------------------------------------

    def _expire_stale_unsellables(self) -> None:
        """Remove entries whose 12-hour decay window has passed."""
        now = time.time()
        expired = [
            sym for sym, ts in self._unsellable_positions.items()
            if (now - ts) >= UNSELLABLE_DECAY_HOURS * 3600
        ]
        for sym in expired:
            del self._unsellable_positions[sym]
            logger.info("♻️  Unsellable decay expired for %s — will retry on next cycle", sym)

    def _mark_unsellable(self, symbol: str) -> None:
        """Tag *symbol* as unsellable.  First tag wins (preserves original timestamp)."""
        if symbol not in self._unsellable_positions:
            self._unsellable_positions[symbol] = time.time()
            logger.warning(
                "🔒 CAP RESOLUTION: %s marked unsellable for %.0fh — excluded from cap math",
                symbol, UNSELLABLE_DECAY_HOURS,
            )

    def _is_tradable(self, symbol: str) -> bool:
        """Return True when *symbol* is NOT in the active unsellable window."""
        return symbol not in self._unsellable_positions

    def _get_tradable_positions(self, positions: List[Dict]) -> List[Dict]:
        """
        Filter *positions* to only those that are currently tradable.

        CAP RESOLUTION ENGINE: unsellable positions are excluded so they
        do not inflate the cap count and block new legitimate entries.
        """
        tradable = [p for p in positions if self._is_tradable(p.get("symbol", ""))]
        excluded = len(positions) - len(tradable)
        if excluded:
            logger.info(
                "🔒 CAP RESOLUTION: excluded %d unsellable position(s) from cap math",
                excluded,
            )
        return tradable

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

        PERFECT CLEANUP FLOW:
        - Single pass — zero retry loops, zero repeated enforcement cycles.
        - Failed sells mark the position unsellable (12h decay) instead of retrying.

        CAP RESOLUTION ENGINE:
        - Only tradable positions count toward the cap.
        - Unsellable positions are excluded from cap math so they never
          permanently block new legitimate entries.

        Returns:
            (success: bool, result_dict with counts and actions)
        """
        logger.info(f"🔍 ENFORCE: Checking position cap (max={self.max_positions})...")

        # Expire any unsellable entries whose 12h window has passed.
        self._expire_stale_unsellables()

        all_positions = self.get_current_positions()

        # CAP RESOLUTION ENGINE: only tradable positions count toward the cap.
        tradable = self._get_tradable_positions(all_positions)
        unsellable_count = len(all_positions) - len(tradable)
        current_count = len(tradable)

        logger.info(
            f"   Tradable positions: {current_count}  |  "
            f"Unsellable (excluded): {unsellable_count}"
        )

        if current_count <= self.max_positions:
            logger.info(f"✅ COMPLIANT: {current_count}/{self.max_positions} tradable positions (under cap)")
            return True, {
                'current_count': current_count,
                'max_allowed': self.max_positions,
                'excess': 0,
                'sold': 0,
                'unsellable_excluded': unsellable_count,
                'status': 'compliant',
            }

        # Over cap: liquidate excess in a single pass (PERFECT CLEANUP FLOW).
        excess = current_count - self.max_positions
        logger.warning(f"🚨 VIOLATION: {excess} tradable position(s) over cap! Auto-liquidating...")
        logger.warning(f"   Strategy: KEEP {self.max_positions} largest, SELL {excess} smallest")

        ranked = self.rank_positions_for_liquidation(tradable)
        sold_count = 0
        failed_count = 0

        for pos in ranked[:excess]:
            symbol = pos.get("symbol", "")
            if self.sell_position(pos):
                sold_count += 1
                time.sleep(1)  # Rate-limit API calls
            else:
                # PERFECT CLEANUP FLOW: do NOT retry.  Mark as unsellable so the
                # CAP RESOLUTION ENGINE excludes it from future cap math until the
                # 12h decay window expires.
                self._mark_unsellable(symbol)
                failed_count += 1
                logger.warning(
                    "⚠️  Sell failed for %s — marked unsellable for %.0fh, continuing cleanup",
                    symbol, UNSELLABLE_DECAY_HOURS,
                )

        compliant = (current_count - sold_count) <= self.max_positions
        status = 'compliant' if compliant else 'partial_unsellable'

        logger.info(
            f"\n{'='*70}\n"
            f"ENFORCEMENT SUMMARY: sold={sold_count}/{excess}, "
            f"unsellable={failed_count}, excluded={unsellable_count}\n"
            f"{'='*70}"
        )

        return compliant, {
            'current_count': current_count - sold_count,
            'max_allowed': self.max_positions,
            'excess': excess,
            'sold': sold_count,
            'failed': failed_count,
            'unsellable_excluded': unsellable_count,
            'status': status,
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
