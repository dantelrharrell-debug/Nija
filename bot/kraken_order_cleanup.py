"""
NIJA Kraken Order Cleanup Module
=================================

Automatically cancels stale open orders on Kraken to free up capital.

This module addresses the issue where limit orders sit unfilled on the order book,
tying up capital that could be used for new profitable trades.

Key Features:
- Cancels open orders older than threshold (default: 5 minutes)
- Frees up held capital for active trading
- Runs automatically during trading cycles
- Supports dry-run mode for testing

Author: NIJA Trading Systems
Version: 1.0
Date: January 23, 2026
"""

import logging
import time
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta

logger = logging.getLogger("nija.kraken_cleanup")


class KrakenOrderCleanup:
    """
    Manages automatic cleanup of stale Kraken orders to free up capital.
    
    This prevents the bot from having excessive capital tied up in unfilled
    limit orders, ensuring funds are available for new profitable trades.
    """
    
    def __init__(self, kraken_broker, max_order_age_minutes: int = 5):
        """
        Initialize Kraken order cleanup manager.
        
        Args:
            kraken_broker: KrakenBrokerAdapter instance
            max_order_age_minutes: Maximum age for open orders before cancellation (default: 5 minutes)
        """
        self.broker = kraken_broker
        self.max_order_age_minutes = max_order_age_minutes
        self.max_order_age_seconds = max_order_age_minutes * 60
        
        # Statistics
        self.total_cleanups = 0
        self.total_orders_cancelled = 0
        self.total_capital_freed = 0.0
        self.last_cleanup_time = None
        
        logger.info("✅ Kraken Order Cleanup initialized")
        logger.info(f"   Max order age: {max_order_age_minutes} minutes")
    
    def get_open_orders(self) -> List[Dict]:
        """
        Get all open orders from Kraken.
        
        Returns:
            List of open order dictionaries with order_id, pair, type, volume, etc.
        """
        try:
            if not self.broker or not self.broker.api:
                logger.warning("⚠️ Kraken API not available for order cleanup")
                return []
            
            # Use the broker's internal API call method
            result = self.broker._kraken_api_call('OpenOrders')
            
            if result and 'result' in result:
                open_orders = result['result'].get('open', {})
                orders = []
                
                for order_id, order in open_orders.items():
                    descr = order.get('descr', {})
                    
                    # Parse order creation time (opentm is Unix timestamp)
                    opentm = order.get('opentm', 0)
                    
                    # Calculate age, ensuring no negative values from clock skew
                    age_seconds = max(0, time.time() - opentm) if opentm > 0 else 0
                    
                    # Calculate capital tied up in unfilled portion of order
                    # For partially filled orders, only count the unfilled portion
                    volume = float(order.get('vol', 0))
                    vol_exec = float(order.get('vol_exec', 0))
                    price = float(descr.get('price', 0))
                    unfilled_volume = volume - vol_exec
                    cost = unfilled_volume * price if price > 0 else float(order.get('cost', 0))
                    
                    orders.append({
                        'order_id': order_id,
                        'pair': descr.get('pair', 'UNKNOWN'),
                        'type': descr.get('type', 'UNKNOWN'),  # 'buy' or 'sell'
                        'ordertype': descr.get('ordertype', 'UNKNOWN'),  # 'limit', 'market', etc.
                        'price': price,
                        'volume': volume,
                        'vol_exec': vol_exec,
                        'cost': cost,
                        'status': order.get('status', 'unknown'),
                        'opentm': opentm,
                        'age_seconds': age_seconds
                    })
                
                return orders
            
            return []
            
        except Exception as e:
            logger.error(f"❌ Error fetching Kraken open orders: {e}")
            return []
    
    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel a specific order on Kraken.
        
        Args:
            order_id: Kraken transaction ID
            
        Returns:
            True if cancelled successfully, False otherwise
        """
        try:
            if not self.broker:
                return False
            
            success = self.broker.cancel_order(order_id)
            return success
            
        except Exception as e:
            logger.error(f"❌ Error cancelling order {order_id}: {e}")
            return False
    
    def cleanup_stale_orders(self, dry_run: bool = False) -> Tuple[int, float]:
        """
        Cancel all open orders older than the maximum age threshold.
        
        This frees up capital held in unfilled limit orders, making it
        available for new profitable trades.
        
        Args:
            dry_run: If True, only report what would be cancelled (don't actually cancel)
            
        Returns:
            Tuple of (orders_cancelled, capital_freed_usd)
        """
        self.total_cleanups += 1
        self.last_cleanup_time = datetime.now()
        
        logger.info("🧹 Kraken order cleanup: Checking for stale orders...")
        
        # Get all open orders
        open_orders = self.get_open_orders()
        
        if not open_orders:
            logger.info("   ✅ No open orders found - nothing to clean up")
            return (0, 0.0)
        
        logger.info(f"   📋 Found {len(open_orders)} open order(s)")
        
        # Identify stale orders
        stale_orders = []
        for order in open_orders:
            age_seconds = order['age_seconds']
            age_minutes = age_seconds / 60.0
            
            if age_seconds >= self.max_order_age_seconds:
                stale_orders.append(order)
                logger.info(f"   🕐 Stale order: {order['pair']} {order['type']} "
                          f"${order['cost']:.2f} (age: {age_minutes:.1f} min)")
        
        if not stale_orders:
            logger.info(f"   ✅ No stale orders (all < {self.max_order_age_minutes} minutes old)")
            return (0, 0.0)
        
        # Calculate total capital to be freed
        capital_to_free = sum(order['cost'] for order in stale_orders)
        
        logger.info(f"   🔴 Cancelling {len(stale_orders)} stale order(s) to free ${capital_to_free:.2f}")
        
        if dry_run:
            logger.info("   🔍 DRY RUN: Would cancel the above orders")
            return (len(stale_orders), capital_to_free)
        
        # Cancel stale orders
        cancelled_count = 0
        for order in stale_orders:
            order_id = order['order_id']
            try:
                success = self.cancel_order(order_id)
                if success:
                    logger.info(f"   ✅ Cancelled: {order['pair']} (freed ${order['cost']:.2f})")
                    cancelled_count += 1
                else:
                    logger.warning(f"   ⚠️ Failed to cancel: {order['pair']}")
                
                # Small delay to avoid rate limiting
                time.sleep(0.1)
                
            except Exception as e:
                logger.error(f"   ❌ Error cancelling {order['pair']}: {e}")
        
        # Update statistics
        self.total_orders_cancelled += cancelled_count
        self.total_capital_freed += capital_to_free
        
        logger.info(f"   📊 Cleanup complete: {cancelled_count}/{len(stale_orders)} orders cancelled")
        logger.info(f"   💰 Capital freed: ${capital_to_free:.2f}")
        
        return (cancelled_count, capital_to_free)
    
    def force_cancel_all_orders(self, dry_run: bool = False) -> Tuple[int, float]:
        """
        Force cancel ALL open orders regardless of age.
        
        Use this for emergency cleanup or account reset.
        
        Args:
            dry_run: If True, only report what would be cancelled
            
        Returns:
            Tuple of (orders_cancelled, capital_freed_usd)
        """
        logger.warning("⚠️ Force cancelling ALL open orders on Kraken...")
        
        # Get all open orders
        open_orders = self.get_open_orders()
        
        if not open_orders:
            logger.info("   ✅ No open orders found")
            return (0, 0.0)
        
        logger.warning(f"   🔴 Found {len(open_orders)} order(s) to cancel")
        
        # Calculate total capital
        capital_to_free = sum(order['cost'] for order in open_orders)
        
        if dry_run:
            logger.info("   🔍 DRY RUN: Would cancel all orders")
            return (len(open_orders), capital_to_free)
        
        # Cancel all orders
        cancelled_count = 0
        for order in open_orders:
            order_id = order['order_id']
            try:
                success = self.cancel_order(order_id)
                if success:
                    logger.info(f"   ✅ Cancelled: {order['pair']}")
                    cancelled_count += 1
                else:
                    logger.warning(f"   ⚠️ Failed to cancel: {order['pair']}")
                
                time.sleep(0.1)
                
            except Exception as e:
                logger.error(f"   ❌ Error cancelling {order['pair']}: {e}")
        
        logger.info(f"   📊 Force cancel complete: {cancelled_count}/{len(open_orders)} cancelled")
        logger.info(f"   💰 Capital freed: ${capital_to_free:.2f}")
        
        return (cancelled_count, capital_to_free)
    
    def get_statistics(self) -> Dict:
        """
        Get cleanup statistics.
        
        Returns:
            Dictionary with cleanup statistics
        """
        return {
            'total_cleanups': self.total_cleanups,
            'total_orders_cancelled': self.total_orders_cancelled,
            'total_capital_freed': self.total_capital_freed,
            'last_cleanup_time': self.last_cleanup_time,
            'max_order_age_minutes': self.max_order_age_minutes
        }
    
    def should_run_cleanup(self, min_interval_minutes: int = 5) -> bool:
        """
        Check if enough time has passed since last cleanup to run again.
        
        Args:
            min_interval_minutes: Minimum minutes between cleanups
            
        Returns:
            True if cleanup should run, False otherwise
        """
        if self.last_cleanup_time is None:
            return True
        
        time_since_cleanup = datetime.now() - self.last_cleanup_time
        return time_since_cleanup.total_seconds() >= (min_interval_minutes * 60)


def create_kraken_cleanup(kraken_broker, max_order_age_minutes: int = 5) -> Optional[KrakenOrderCleanup]:
    """
    Factory function to create a Kraken order cleanup instance.
    
    Args:
        kraken_broker: KrakenBrokerAdapter instance
        max_order_age_minutes: Maximum age for orders before cancellation
        
    Returns:
        KrakenOrderCleanup instance or None if broker is invalid
    """
    if not kraken_broker:
        logger.warning("⚠️ Cannot create Kraken cleanup: broker is None")
        return None
    
    try:
        cleanup = KrakenOrderCleanup(kraken_broker, max_order_age_minutes)
        return cleanup
    except Exception as e:
        logger.error(f"❌ Failed to create Kraken cleanup: {e}")
        return None
