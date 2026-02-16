#!/usr/bin/env python3
"""
Broker-Level Dust Position Cleanup
===================================
Implements immediate cleanup of dust positions (< $1 USD) at the broker level.

This module:
1. Fetches ALL positions from broker API (not just tracked positions)
2. Identifies positions below $1 USD threshold
3. Closes/liquidates dust positions physically at broker level
4. Logs all cleanup actions for audit trail

Priority: IMMEDIATE (Issue #1)
"""

import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Dust threshold - positions below this are considered dust
DUST_THRESHOLD_USD = 1.00


@dataclass
class DustPosition:
    """Represents a dust position to be cleaned up"""
    symbol: str
    quantity: float
    usd_value: float
    currency: str
    source: str  # 'broker' or 'tracked'


class BrokerDustCleanup:
    """
    Cleans up dust positions at the broker level.
    
    This is different from tracked position cleanup - it works directly
    with broker API to find and close ALL dust positions, including:
    - Legacy positions from manual trading
    - Positions adopted from other bots
    - Remnants from failed orders
    - Partially filled orders
    """
    
    def __init__(self,
                 dust_threshold_usd: float = DUST_THRESHOLD_USD,
                 dry_run: bool = False):
        """
        Initialize broker dust cleanup.
        
        Args:
            dust_threshold_usd: USD value threshold for dust positions
            dry_run: If True, log actions but don't execute trades
        """
        self.dust_threshold_usd = dust_threshold_usd
        self.dry_run = dry_run
        
        logger.info("🧹 Broker Dust Cleanup Engine initialized:")
        logger.info(f"   Dust Threshold: ${dust_threshold_usd:.2f} USD")
        logger.info(f"   Dry Run: {'ENABLED (no actual trades)' if dry_run else 'DISABLED (live cleanup)'}")
    
    def find_dust_positions(self, broker) -> List[DustPosition]:
        """
        Find all dust positions from broker.
        
        Args:
            broker: Broker instance with get_positions() method
            
        Returns:
            List of DustPosition objects
        """
        dust_positions = []
        
        try:
            # Fetch all positions from broker
            logger.info("🔍 Fetching all positions from broker...")
            positions = broker.get_positions()
            
            if not positions:
                logger.info("   No positions found at broker level")
                return []
            
            logger.info(f"   Found {len(positions)} total positions")
            
            # Check each position for dust
            for pos in positions:
                symbol = pos.get('symbol', 'UNKNOWN')
                quantity = float(pos.get('quantity', 0))
                currency = pos.get('currency', symbol.split('-')[0] if '-' in symbol else symbol)
                
                # Get current price to calculate USD value
                try:
                    current_price = broker.get_current_price(symbol)
                    if current_price <= 0:
                        logger.warning(f"   ⚠️  Could not get price for {symbol}, skipping")
                        continue
                    
                    usd_value = quantity * current_price
                    
                    # Check if it's dust
                    if usd_value < self.dust_threshold_usd:
                        dust_pos = DustPosition(
                            symbol=symbol,
                            quantity=quantity,
                            usd_value=usd_value,
                            currency=currency,
                            source='broker'
                        )
                        dust_positions.append(dust_pos)
                        logger.info(f"   🗑️  DUST: {symbol} - ${usd_value:.4f} ({quantity:.8f} {currency})")
                
                except Exception as e:
                    logger.error(f"   ❌ Error checking {symbol}: {e}")
                    continue
            
            if dust_positions:
                logger.warning(f"🚨 Found {len(dust_positions)} dust positions to clean up:")
                total_dust_value = sum(p.usd_value for p in dust_positions)
                logger.warning(f"   Total dust value: ${total_dust_value:.4f}")
            else:
                logger.info("✅ No dust positions found")
            
            return dust_positions
        
        except Exception as e:
            logger.error(f"❌ Error finding dust positions: {e}")
            return []
    
    def close_dust_position(self, broker, dust_pos: DustPosition) -> Tuple[bool, str]:
        """
        Close a single dust position.
        
        Args:
            broker: Broker instance
            dust_pos: DustPosition to close
            
        Returns:
            Tuple of (success: bool, message: str)
        """
        if self.dry_run:
            logger.info(f"   [DRY RUN] Would close {dust_pos.symbol}: ${dust_pos.usd_value:.4f}")
            return True, "Dry run - no action taken"
        
        try:
            logger.info(f"🔨 Closing dust position: {dust_pos.symbol}")
            logger.info(f"   Quantity: {dust_pos.quantity:.8f} {dust_pos.currency}")
            logger.info(f"   USD Value: ${dust_pos.usd_value:.4f}")
            
            # Place market sell order to close position
            result = broker.place_market_order(
                symbol=dust_pos.symbol,
                side='sell',
                quantity=dust_pos.quantity,
                size_type='base',  # Sell exact quantity we have
                force_liquidate=True,  # Force close even if below minimum
                ignore_min_trade=True  # Ignore minimum trade size for dust cleanup
            )
            
            if result and result.get('status') in ['filled', 'completed', 'success']:
                logger.info(f"   ✅ Successfully closed {dust_pos.symbol}")
                return True, "Position closed successfully"
            else:
                logger.error(f"   ❌ Failed to close {dust_pos.symbol}: {result}")
                return False, f"Order failed: {result}"
        
        except Exception as e:
            logger.error(f"   ❌ Exception closing {dust_pos.symbol}: {e}")
            return False, f"Exception: {str(e)}"
    
    def cleanup_all_dust(self, broker) -> Dict[str, any]:
        """
        Find and close all dust positions.
        
        Args:
            broker: Broker instance
            
        Returns:
            Dict with cleanup statistics
        """
        logger.info("=" * 70)
        logger.info("🧹 STARTING BROKER-LEVEL DUST CLEANUP")
        logger.info("=" * 70)
        
        start_time = datetime.now()
        
        # Find all dust positions
        dust_positions = self.find_dust_positions(broker)
        
        if not dust_positions:
            logger.info("✅ No dust positions to clean up")
            return {
                'total_found': 0,
                'closed': 0,
                'failed': 0,
                'total_value_cleaned': 0.0,
                'duration_seconds': 0
            }
        
        # Close each dust position
        closed = 0
        failed = 0
        total_value_cleaned = 0.0
        
        for dust_pos in dust_positions:
            success, message = self.close_dust_position(broker, dust_pos)
            
            if success:
                closed += 1
                total_value_cleaned += dust_pos.usd_value
            else:
                failed += 1
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        # Summary
        logger.info("=" * 70)
        logger.info("🧹 DUST CLEANUP COMPLETE")
        logger.info("=" * 70)
        logger.info(f"   Total Found: {len(dust_positions)}")
        logger.info(f"   Successfully Closed: {closed}")
        logger.info(f"   Failed: {failed}")
        logger.info(f"   Total Value Cleaned: ${total_value_cleaned:.4f}")
        logger.info(f"   Duration: {duration:.2f}s")
        logger.info("=" * 70)
        
        return {
            'total_found': len(dust_positions),
            'closed': closed,
            'failed': failed,
            'total_value_cleaned': total_value_cleaned,
            'duration_seconds': duration,
            'timestamp': datetime.now().isoformat()
        }


# Global singleton instance
_broker_dust_cleanup: Optional[BrokerDustCleanup] = None


def get_broker_dust_cleanup(dust_threshold_usd: float = DUST_THRESHOLD_USD,
                            dry_run: bool = False) -> BrokerDustCleanup:
    """
    Get global broker dust cleanup instance (singleton).
    
    Args:
        dust_threshold_usd: USD value threshold for dust positions
        dry_run: If True, log actions but don't execute trades
        
    Returns:
        BrokerDustCleanup: Global cleanup instance
    """
    global _broker_dust_cleanup
    
    if _broker_dust_cleanup is None:
        _broker_dust_cleanup = BrokerDustCleanup(
            dust_threshold_usd=dust_threshold_usd,
            dry_run=dry_run
        )
    
    return _broker_dust_cleanup
