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
DUST_THRESHOLD_USD = 1.00  # USD value threshold for dust positions (consistent with broker)

# Add bot dir to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

try:
    from broker_manager import CoinbaseBroker
except ImportError:
    logger.error("Failed to import broker_manager")
    CoinbaseBroker = None


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
        logger.info(f"PositionCapEnforcer initialized: max={max_positions} positions")
    
    def get_current_positions(self) -> List[Dict]:
        """
        Fetch current crypto holdings from broker.
        
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
            for pos in positions:
                symbol = pos.get('symbol', '')
                currency = pos.get('currency', symbol.split('-')[0] if '-' in symbol else symbol)
                balance = float(pos.get('quantity', 0))
                
                if balance <= 0:
                    continue
                
                # Try to get current price
                try:
                    price = self.broker.get_current_price(symbol)
                    if price <= 0:
                        price = 1.0  # Fallback if price unavailable
                    usd_value = balance * price

                    # CRITICAL FIX: Only skip TRUE dust to match broker.get_positions()
                    # Small positions like $0.04-$0.15 MUST be counted and managed
                    if balance <= 0 or usd_value < DUST_THRESHOLD_USD:
                        logger.info(f"Skipping dust position {symbol}: balance={balance}, usd_value={usd_value:.4f}")
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
            
            return result
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return []
    
    def rank_positions_for_liquidation(self, positions: List[Dict]) -> List[Dict]:
        """
        Rank positions by priority for liquidation.
        
        Strategy: Prioritize smallest positions to minimize capital impact.
        Future: Consider P&L, momentum, RSI when entry price tracking is available.
        
        Args:
            positions: List of position dicts
        
        Returns:
            Ranked list (highest-priority-to-sell first)
        """
        # Rank by smallest USD value (minimal capital impact, easier to exit)
        # This prevents force-selling large winning positions
        ranked = sorted(positions, key=lambda p: p['usd_value'])
        
        logger.info(f"Ranked {len(ranked)} positions for liquidation (smallest first):")
        for i, pos in enumerate(ranked, 1):
            logger.info(f"  {i}. {pos['symbol']}: ${pos['usd_value']:.2f}")
        
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
        
        Returns:
            (success: bool, result_dict with counts and actions)
        """
        logger.info(f"🔍 ENFORCE: Checking position cap (max={self.max_positions})...")
        
        positions = self.get_current_positions()
        current_count = len(positions)
        
        logger.info(f"   Current positions: {current_count}")
        
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
