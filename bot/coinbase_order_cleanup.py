"""
NIJA Coinbase Order Cleanup Module
====================================

Automatically cancels stale open orders on Coinbase to free up capital.

This module addresses the issue where market or limit orders sit unfilled,
tying up capital that could be used for new profitable trades.

Key Features:
- Cancels open orders older than threshold (default: 5 minutes)
- Frees up held capital for active trading
- Runs automatically during trading cycles
- Supports dry-run mode for testing

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

import logging
import time
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timezone

logger = logging.getLogger("nija.coinbase_cleanup")


class CoinbaseOrderCleanup:
    """
    Manages automatic cleanup of stale Coinbase Advanced Trade orders to free up capital.

    This prevents the bot from having excessive capital tied up in unfilled
    orders, ensuring funds are available for new profitable trades.
    """

    def __init__(self, coinbase_broker, max_order_age_minutes: int = 5):
        """
        Initialize Coinbase order cleanup manager.

        Args:
            coinbase_broker: CoinbaseBroker instance (from broker_manager.py)
            max_order_age_minutes: Maximum age for open orders before cancellation (default: 5 minutes)
        """
        self.broker = coinbase_broker
        self.max_order_age_minutes = max_order_age_minutes
        self.max_order_age_seconds = max_order_age_minutes * 60

        # Statistics
        self.total_cleanups = 0
        self.total_orders_cancelled = 0
        self.total_capital_freed = 0.0
        self.last_cleanup_time: Optional[datetime] = None

        logger.info("✅ Coinbase Order Cleanup initialized")
        logger.info(f"   Max order age: {max_order_age_minutes} minutes")

    def get_open_orders(self) -> List[Dict]:
        """
        Get all open orders from Coinbase Advanced Trade API.

        Returns:
            List of open order dictionaries with order_id, symbol, side, cost, age, etc.
        """
        try:
            client = getattr(self.broker, 'client', None)
            if client is None:
                logger.warning("⚠️ Coinbase client not available for order cleanup")
                return []

            resp = client.list_orders(order_status=["OPEN"])
            raw_orders = getattr(resp, 'orders', None)
            if isinstance(resp, dict):
                raw_orders = resp.get('orders', [])
            if not raw_orders:
                return []

            orders = []
            now_ts = time.time()

            for order in raw_orders:
                if isinstance(order, dict):
                    order_id    = order.get('order_id', '')
                    product_id  = order.get('product_id', 'UNKNOWN')
                    side        = order.get('side', 'UNKNOWN')
                    order_type  = order.get('order_type', 'UNKNOWN')
                    created_raw = order.get('created_time', '')
                    # Outstanding (unfilled) value
                    outstanding = order.get('outstanding_hold_amount', '0')
                    try:
                        cost = float(outstanding) if outstanding else 0.0
                    except (ValueError, TypeError):
                        cost = 0.0
                else:
                    order_id    = getattr(order, 'order_id', '')
                    product_id  = getattr(order, 'product_id', 'UNKNOWN')
                    side        = getattr(order, 'side', 'UNKNOWN')
                    order_type  = getattr(order, 'order_type', 'UNKNOWN')
                    created_raw = getattr(order, 'created_time', '')
                    outstanding = getattr(order, 'outstanding_hold_amount', '0')
                    try:
                        cost = float(outstanding) if outstanding else 0.0
                    except (ValueError, TypeError):
                        cost = 0.0

                # Parse ISO-8601 timestamp → age in seconds
                age_seconds = 0.0
                if created_raw:
                    try:
                        # Coinbase returns RFC 3339 / ISO 8601 strings like
                        # "2024-01-15T12:34:56.789Z"
                        if created_raw.endswith('Z'):
                            created_raw = created_raw[:-1] + '+00:00'
                        created_dt = datetime.fromisoformat(created_raw)
                        if created_dt.tzinfo is None:
                            created_dt = created_dt.replace(tzinfo=timezone.utc)
                        created_ts = created_dt.timestamp()
                        age_seconds = max(0.0, now_ts - created_ts)
                    except Exception:
                        age_seconds = 0.0

                if not order_id:
                    continue

                orders.append({
                    'order_id':    order_id,
                    'pair':        product_id,
                    'type':        side,
                    'ordertype':   order_type,
                    'cost':        cost,
                    'created_raw': created_raw,
                    'age_seconds': age_seconds,
                })

            return orders

        except Exception as e:
            logger.error(f"❌ Error fetching Coinbase open orders: {e}")
            return []

    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel a specific order on Coinbase.

        Args:
            order_id: Coinbase order ID

        Returns:
            True if cancelled successfully, False otherwise
        """
        try:
            client = getattr(self.broker, 'client', None)
            if client is None:
                return False

            resp = client.cancel_orders(order_ids=[order_id])
            results = getattr(resp, 'results', None)
            if isinstance(resp, dict):
                results = resp.get('results', [])
            if results:
                first = results[0]
                success = getattr(first, 'success', None)
                if isinstance(first, dict):
                    success = first.get('success')
                if success is False:
                    return False
            return True

        except Exception as e:
            logger.error(f"❌ Error cancelling Coinbase order {order_id}: {e}")
            return False

    def cleanup_stale_orders(self, dry_run: bool = False) -> Tuple[int, float]:
        """
        Cancel all open orders older than the maximum age threshold.

        This frees up capital held in unfilled orders, making it available
        for new profitable trades.

        Args:
            dry_run: If True, only report what would be cancelled (don't actually cancel)

        Returns:
            Tuple of (orders_cancelled, capital_freed_usd)
        """
        self.total_cleanups += 1
        self.last_cleanup_time = datetime.now()

        logger.info("🧹 Coinbase order cleanup: Checking for stale orders...")

        open_orders = self.get_open_orders()

        if not open_orders:
            logger.info("   ✅ No open orders found - nothing to clean up")
            return (0, 0.0)

        logger.info(f"   📋 Found {len(open_orders)} open order(s)")

        stale_orders = []
        for order in open_orders:
            age_seconds = order['age_seconds']
            age_minutes = age_seconds / 60.0

            if age_seconds >= self.max_order_age_seconds:
                stale_orders.append(order)
                logger.info(
                    f"   🕐 Stale order: {order['pair']} {order['type']} "
                    f"${order['cost']:.2f} (age: {age_minutes:.1f} min)"
                )

        if not stale_orders:
            logger.info(f"   ✅ No stale orders (all < {self.max_order_age_minutes} minutes old)")
            return (0, 0.0)

        capital_to_free = sum(order['cost'] for order in stale_orders)
        logger.info(
            f"   🔴 Cancelling {len(stale_orders)} stale order(s) to free ${capital_to_free:.2f}"
        )

        if dry_run:
            logger.info("   🔍 DRY RUN: Would cancel the above orders")
            return (len(stale_orders), capital_to_free)

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

        self.total_orders_cancelled += cancelled_count
        self.total_capital_freed += capital_to_free

        logger.info(
            f"   📊 Cleanup complete: {cancelled_count}/{len(stale_orders)} orders cancelled"
        )
        logger.info(f"   💰 Capital freed: ${capital_to_free:.2f}")

        return (cancelled_count, capital_to_free)

    def get_statistics(self) -> Dict:
        """Return cleanup statistics."""
        return {
            'total_cleanups':         self.total_cleanups,
            'total_orders_cancelled': self.total_orders_cancelled,
            'total_capital_freed':    self.total_capital_freed,
            'last_cleanup_time':      self.last_cleanup_time,
            'max_order_age_minutes':  self.max_order_age_minutes,
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
        elapsed = (datetime.now() - self.last_cleanup_time).total_seconds()
        return elapsed >= (min_interval_minutes * 60)


def create_coinbase_cleanup(
    coinbase_broker, max_order_age_minutes: int = 5
) -> Optional[CoinbaseOrderCleanup]:
    """
    Factory function to create a Coinbase order cleanup instance.

    Args:
        coinbase_broker: CoinbaseBroker instance
        max_order_age_minutes: Maximum age for orders before cancellation

    Returns:
        CoinbaseOrderCleanup instance or None if broker is invalid
    """
    if not coinbase_broker:
        logger.warning("⚠️ Cannot create Coinbase cleanup: broker is None")
        return None

    try:
        cleanup = CoinbaseOrderCleanup(coinbase_broker, max_order_age_minutes)
        return cleanup
    except Exception as e:
        logger.error(f"❌ Failed to create Coinbase cleanup: {e}")
        return None
