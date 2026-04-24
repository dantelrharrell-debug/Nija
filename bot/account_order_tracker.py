"""
NIJA Account Order Tracker
===========================

Comprehensive order tracking per account to address:
1. Count open orders per account
2. Track held capital per account
3. Prevent order fragmentation in micro accounts
4. Ensure no double-reservation of margin
5. Clean up orders after filled trades

Author: NIJA Trading Systems
Date: February 17, 2026
Version: 1.0
"""

import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from collections import defaultdict
import json
from pathlib import Path

logger = logging.getLogger("nija.account_order_tracker")


@dataclass
class OrderInfo:
    """Detailed order information"""
    order_id: str
    account_id: str
    symbol: str
    side: str  # 'buy' or 'sell'
    price: float
    quantity: float
    size_usd: float
    status: str  # 'open', 'filled', 'cancelled'
    created_at: datetime
    filled_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    order_type: str = 'market'  # 'market', 'limit', 'stop', 'target'
    parent_position_id: Optional[str] = None  # For stop/target orders
    reserved_capital: float = 0.0  # Capital reserved for this order
    
    def age_seconds(self) -> float:
        """Get order age in seconds"""
        return (datetime.now() - self.created_at).total_seconds()
    
    def age_minutes(self) -> float:
        """Get order age in minutes"""
        return self.age_seconds() / 60.0
    
    def is_stale(self, max_age_minutes: int = 60) -> bool:
        """Check if order is stale (older than threshold)"""
        return self.age_minutes() > max_age_minutes
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization"""
        return {
            'order_id': self.order_id,
            'account_id': self.account_id,
            'symbol': self.symbol,
            'side': self.side,
            'price': self.price,
            'quantity': self.quantity,
            'size_usd': self.size_usd,
            'status': self.status,
            'created_at': self.created_at.isoformat(),
            'filled_at': self.filled_at.isoformat() if self.filled_at else None,
            'cancelled_at': self.cancelled_at.isoformat() if self.cancelled_at else None,
            'order_type': self.order_type,
            'parent_position_id': self.parent_position_id,
            'reserved_capital': self.reserved_capital,
        }


@dataclass
class AccountOrderStats:
    """Statistics for orders per account"""
    account_id: str
    total_open_orders: int = 0
    market_orders: int = 0
    stop_orders: int = 0
    target_orders: int = 0
    total_held_capital: float = 0.0
    oldest_order_age_minutes: float = 0.0
    stale_orders_count: int = 0
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'account_id': self.account_id,
            'total_open_orders': self.total_open_orders,
            'market_orders': self.market_orders,
            'stop_orders': self.stop_orders,
            'target_orders': self.target_orders,
            'total_held_capital': self.total_held_capital,
            'oldest_order_age_minutes': self.oldest_order_age_minutes,
            'stale_orders_count': self.stale_orders_count,
        }


class AccountOrderTracker:
    """
    Comprehensive order tracker per account
    
    Features:
    - Track all orders per account
    - Monitor held capital per account
    - Detect order fragmentation
    - Verify no double-reservation of margin
    - Cleanup orders after fills
    """
    
    def __init__(self, data_dir: str = "./data"):
        """Initialize account order tracker"""
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True, parents=True)
        self.state_file = self.data_dir / "account_orders_state.json"
        
        # Track orders by account
        self.orders_by_account: Dict[str, List[OrderInfo]] = defaultdict(list)
        
        # Track reserved capital by account
        self.reserved_capital_by_account: Dict[str, float] = defaultdict(float)
        
        # Track cleanup stats
        self.cleanup_stats = {
            'total_cleaned': 0,
            'last_cleanup': None,
            'orders_cleaned_per_account': defaultdict(int)
        }
        
        # Configuration
        self.max_order_age_minutes = 60  # Default: orders older than 60 minutes are stale
        self.auto_cleanup_stale_orders = True
        
        logger.info("✅ Account Order Tracker initialized")
        
        # Load existing state
        self._load_state()
    
    def add_order(self, order: OrderInfo) -> None:
        """
        Add a new order to tracking
        
        Args:
            order: OrderInfo object to track
        """
        account_id = order.account_id
        
        # Check for duplicate
        if any(o.order_id == order.order_id for o in self.orders_by_account[account_id]):
            logger.warning(f"Order {order.order_id} already tracked for account {account_id}")
            return
        
        # Add to tracking
        self.orders_by_account[account_id].append(order)
        
        # Update reserved capital
        if order.status == 'open':
            self.reserved_capital_by_account[account_id] += order.reserved_capital
        
        logger.debug(f"Added order {order.order_id} for {account_id}: {order.symbol} {order.side} ${order.size_usd:.2f}")
        
        # Save state
        self._save_state()
    
    def mark_order_filled(self, order_id: str, account_id: str) -> bool:
        """
        Mark an order as filled
        
        Args:
            order_id: Order ID to mark as filled
            account_id: Account ID
            
        Returns:
            True if order found and marked, False otherwise
        """
        orders = self.orders_by_account[account_id]
        for order in orders:
            if order.order_id == order_id:
                if order.status == 'open':
                    # Release reserved capital
                    self.reserved_capital_by_account[account_id] -= order.reserved_capital
                
                order.status = 'filled'
                order.filled_at = datetime.now()
                logger.info(f"✅ Order {order_id} marked as FILLED for {account_id}")
                self._save_state()
                return True
        
        logger.warning(f"Order {order_id} not found for account {account_id}")
        return False
    
    def mark_order_cancelled(self, order_id: str, account_id: str) -> bool:
        """
        Mark an order as cancelled and release capital
        
        Args:
            order_id: Order ID to cancel
            account_id: Account ID
            
        Returns:
            True if order found and cancelled, False otherwise
        """
        orders = self.orders_by_account[account_id]
        for order in orders:
            if order.order_id == order_id:
                if order.status == 'open':
                    # Release reserved capital
                    self.reserved_capital_by_account[account_id] -= order.reserved_capital
                
                order.status = 'cancelled'
                order.cancelled_at = datetime.now()
                logger.info(f"🚫 Order {order_id} marked as CANCELLED for {account_id}")
                self._save_state()
                return True
        
        logger.warning(f"Order {order_id} not found for account {account_id}")
        return False
    
    def get_open_orders(self, account_id: str) -> List[OrderInfo]:
        """
        Get all open orders for an account
        
        Args:
            account_id: Account ID
            
        Returns:
            List of open OrderInfo objects
        """
        return [o for o in self.orders_by_account[account_id] if o.status == 'open']
    
    def get_order_count(self, account_id: str) -> int:
        """
        Get count of open orders for an account
        
        Args:
            account_id: Account ID
            
        Returns:
            Number of open orders
        """
        return len(self.get_open_orders(account_id))
    
    def get_held_capital(self, account_id: str) -> float:
        """
        Get total capital held by open orders for an account
        
        Args:
            account_id: Account ID
            
        Returns:
            Total held capital in USD
        """
        return self.reserved_capital_by_account[account_id]
    
    def get_account_stats(self, account_id: str) -> AccountOrderStats:
        """
        Get comprehensive order statistics for an account
        
        Args:
            account_id: Account ID
            
        Returns:
            AccountOrderStats object
        """
        open_orders = self.get_open_orders(account_id)
        
        stats = AccountOrderStats(account_id=account_id)
        stats.total_open_orders = len(open_orders)
        stats.total_held_capital = self.get_held_capital(account_id)
        
        # Count by order type
        for order in open_orders:
            if order.order_type == 'market':
                stats.market_orders += 1
            elif order.order_type == 'stop':
                stats.stop_orders += 1
            elif order.order_type == 'target':
                stats.target_orders += 1
            
            # Check if stale
            if order.is_stale(self.max_order_age_minutes):
                stats.stale_orders_count += 1
        
        # Get oldest order age
        if open_orders:
            stats.oldest_order_age_minutes = max(o.age_minutes() for o in open_orders)
        
        return stats
    
    def check_double_reservation(self, position_id: str, account_id: str) -> Tuple[bool, str]:
        """
        Check if a position has multiple orders reserving capital
        (stop + target should not double-reserve)
        
        Args:
            position_id: Position ID to check
            account_id: Account ID
            
        Returns:
            Tuple of (has_double_reservation, details_message)
        """
        open_orders = self.get_open_orders(account_id)
        
        # Find orders for this position
        position_orders = [o for o in open_orders if o.parent_position_id == position_id]
        
        if not position_orders:
            return False, "No orders found for position"
        
        # Calculate total reserved
        total_reserved = sum(o.reserved_capital for o in position_orders)
        
        # Check order types
        order_types = [o.order_type for o in position_orders]
        
        # If we have both stop and target, they should share the same reservation
        # (only reserve once for the position, not twice)
        if 'stop' in order_types and 'target' in order_types:
            # This is OK - both orders exist but should use same capital
            # Check if they reserved separately
            stop_reserved = sum(o.reserved_capital for o in position_orders if o.order_type == 'stop')
            target_reserved = sum(o.reserved_capital for o in position_orders if o.order_type == 'target')
            
            if stop_reserved > 0 and target_reserved > 0:
                # Both reserved capital - this is double-reservation!
                return True, f"DOUBLE RESERVATION: Stop reserved ${stop_reserved:.2f}, Target reserved ${target_reserved:.2f} (total ${total_reserved:.2f})"
        
        return False, f"No double reservation detected (${total_reserved:.2f} reserved for {len(position_orders)} orders)"
    
    def cleanup_filled_orders(self, account_id: Optional[str] = None, max_age_hours: int = 24) -> int:
        """
        Clean up old filled/cancelled orders
        
        Args:
            account_id: Specific account to clean, or None for all accounts
            max_age_hours: Remove orders older than this many hours
            
        Returns:
            Number of orders cleaned up
        """
        cleaned_count = 0
        cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
        
        accounts_to_clean = [account_id] if account_id else list(self.orders_by_account.keys())
        
        for acc_id in accounts_to_clean:
            orders = self.orders_by_account[acc_id]
            
            # Remove old filled/cancelled orders
            before_count = len(orders)
            self.orders_by_account[acc_id] = [
                o for o in orders
                if not (
                    o.status in ['filled', 'cancelled'] and
                    (o.filled_at or o.cancelled_at or o.created_at) < cutoff_time
                )
            ]
            after_count = len(self.orders_by_account[acc_id])
            
            removed = before_count - after_count
            if removed > 0:
                cleaned_count += removed
                self.cleanup_stats['orders_cleaned_per_account'][acc_id] += removed
                logger.info(f"🧹 Cleaned up {removed} old orders for {acc_id}")
        
        if cleaned_count > 0:
            self.cleanup_stats['total_cleaned'] += cleaned_count
            self.cleanup_stats['last_cleanup'] = datetime.now().isoformat()
            self._save_state()
        
        return cleaned_count
    
    def cleanup_stale_orders(self, account_id: Optional[str] = None, force_cancel: bool = False) -> int:
        """
        Identify stale orders (open too long) for cleanup
        
        Args:
            account_id: Specific account to check, or None for all accounts
            force_cancel: If True, mark orders as cancelled (requires broker integration)
            
        Returns:
            Number of stale orders found (or cancelled)
        """
        stale_count = 0
        
        accounts_to_check = [account_id] if account_id else list(self.orders_by_account.keys())
        
        for acc_id in accounts_to_check:
            open_orders = self.get_open_orders(acc_id)
            
            for order in open_orders:
                if order.is_stale(self.max_order_age_minutes):
                    stale_count += 1
                    logger.warning(
                        f"⚠️ Stale order detected for {acc_id}: "
                        f"{order.order_id} ({order.symbol} {order.side}, age: {order.age_minutes():.1f}m)"
                    )
                    
                    if force_cancel:
                        # Mark as cancelled (caller should handle broker API cancellation)
                        self.mark_order_cancelled(order.order_id, acc_id)
        
        return stale_count
    
    def detect_order_fragmentation(self, account_id: str, account_balance: float, warn_threshold: float = 0.30) -> Tuple[bool, str]:
        """
        Detect if orders are fragmenting capital (too many small orders)
        Critical for micro accounts
        
        Args:
            account_id: Account ID to check
            account_balance: Total account balance
            warn_threshold: Warn if held capital exceeds this % of balance
            
        Returns:
            Tuple of (is_fragmented, warning_message)
        """
        held_capital = self.get_held_capital(account_id)
        open_order_count = self.get_order_count(account_id)
        
        if account_balance <= 0:
            return False, "Cannot check fragmentation: zero balance"
        
        held_pct = (held_capital / account_balance) * 100
        
        # Check if too much capital is tied up in orders
        if held_pct > warn_threshold * 100:
            avg_order_size = held_capital / open_order_count if open_order_count > 0 else 0
            return True, (
                f"⚠️ ORDER FRAGMENTATION DETECTED: "
                f"{held_pct:.1f}% of capital (${held_capital:.2f} / ${account_balance:.2f}) "
                f"held in {open_order_count} orders (avg ${avg_order_size:.2f} per order). "
                f"This kills performance in micro accounts!"
            )
        
        return False, f"✅ No fragmentation: {held_pct:.1f}% held in {open_order_count} orders"
    
    def get_all_accounts_summary(self) -> Dict[str, AccountOrderStats]:
        """
        Get summary of all accounts
        
        Returns:
            Dictionary mapping account_id to AccountOrderStats
        """
        return {
            account_id: self.get_account_stats(account_id)
            for account_id in self.orders_by_account.keys()
        }
    
    def _save_state(self) -> None:
        """Save tracker state to file"""
        try:
            state = {
                'orders_by_account': {
                    account_id: [o.to_dict() for o in orders]
                    for account_id, orders in self.orders_by_account.items()
                },
                'reserved_capital_by_account': dict(self.reserved_capital_by_account),
                'cleanup_stats': {
                    'total_cleaned': self.cleanup_stats['total_cleaned'],
                    'last_cleanup': self.cleanup_stats['last_cleanup'],
                    'orders_cleaned_per_account': dict(self.cleanup_stats['orders_cleaned_per_account'])
                },
                'timestamp': datetime.now().isoformat()
            }
            
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2, default=str)
            
        except Exception as e:
            logger.error(f"Failed to save order tracker state: {e}")
    
    def _load_state(self) -> None:
        """Load tracker state from file"""
        if not self.state_file.exists():
            logger.info("No saved order tracker state found (first run)")
            return
        
        try:
            with open(self.state_file, 'r') as f:
                state = json.load(f)
            
            # Restore orders
            for account_id, orders_data in state.get('orders_by_account', {}).items():
                self.orders_by_account[account_id] = [
                    OrderInfo(
                        order_id=o['order_id'],
                        account_id=o['account_id'],
                        symbol=o['symbol'],
                        side=o['side'],
                        price=o['price'],
                        quantity=o['quantity'],
                        size_usd=o['size_usd'],
                        status=o['status'],
                        created_at=datetime.fromisoformat(o['created_at']),
                        filled_at=datetime.fromisoformat(o['filled_at']) if o.get('filled_at') else None,
                        cancelled_at=datetime.fromisoformat(o['cancelled_at']) if o.get('cancelled_at') else None,
                        order_type=o.get('order_type', 'market'),
                        parent_position_id=o.get('parent_position_id'),
                        reserved_capital=o.get('reserved_capital', 0.0)
                    )
                    for o in orders_data
                ]
            
            # Restore reserved capital
            self.reserved_capital_by_account = defaultdict(
                float,
                state.get('reserved_capital_by_account', {})
            )
            
            # Restore cleanup stats
            cleanup = state.get('cleanup_stats', {})
            self.cleanup_stats['total_cleaned'] = cleanup.get('total_cleaned', 0)
            self.cleanup_stats['last_cleanup'] = cleanup.get('last_cleanup')
            self.cleanup_stats['orders_cleaned_per_account'] = defaultdict(
                int,
                cleanup.get('orders_cleaned_per_account', {})
            )
            
            logger.info(f"✅ Loaded order tracker state: {sum(len(orders) for orders in self.orders_by_account.values())} orders across {len(self.orders_by_account)} accounts")
            
        except Exception as e:
            logger.error(f"Failed to load order tracker state: {e}")


# Global instance
_global_order_tracker: Optional[AccountOrderTracker] = None


def get_order_tracker(data_dir: str = "./data") -> AccountOrderTracker:
    """Get or create global order tracker instance"""
    global _global_order_tracker
    if _global_order_tracker is None:
        _global_order_tracker = AccountOrderTracker(data_dir=data_dir)
    return _global_order_tracker
