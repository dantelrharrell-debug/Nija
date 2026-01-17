"""
Integration Example: Using Advanced User Management Features

This example shows how to integrate the new user management features
with the existing NIJA trading bot.
"""

import logging
from typing import Dict, Optional

# Import existing NIJA components
try:
    from bot.broker_manager import KrakenBroker, AccountType
    from controls import get_hard_controls
except ImportError:
    print("This is an example file - imports may not resolve in isolation")

# Import new user management features
from bot.user_nonce_manager import get_user_nonce_manager
from bot.user_pnl_tracker import get_user_pnl_tracker
from bot.user_risk_manager import get_user_risk_manager
from bot.trade_webhook_notifier import get_webhook_notifier

logger = logging.getLogger('nija.integration_example')


class EnhancedUserTradingManager:
    """
    Example integration of user management features with NIJA trading.
    
    This shows how to wrap existing broker functionality with the new
    user management features for comprehensive per-user control.
    """
    
    def __init__(self, user_id: str):
        """
        Initialize enhanced trading manager for a user.
        
        Args:
            user_id: User identifier
        """
        self.user_id = user_id
        
        # Get singletons
        self.nonce_manager = get_user_nonce_manager()
        self.pnl_tracker = get_user_pnl_tracker()
        self.risk_manager = get_user_risk_manager()
        self.webhook_notifier = get_webhook_notifier()
        self.hard_controls = get_hard_controls()
        
        # Initialize broker (example with Kraken)
        self.broker = None
        
        logger.info(f"EnhancedUserTradingManager initialized for {user_id}")
    
    def connect_broker(self, broker_type: str = 'kraken') -> bool:
        """
        Connect to broker with enhanced nonce management.
        
        Args:
            broker_type: Type of broker (kraken, coinbase, etc.)
            
        Returns:
            bool: True if connected successfully
        """
        try:
            if broker_type == 'kraken':
                # Create broker with user account type
                self.broker = KrakenBroker(
                    account_type=AccountType.USER,
                    user_id=self.user_id
                )
                
                # Connect
                if self.broker.connect():
                    # Update balance in risk manager
                    balance = self.broker.get_account_balance()
                    self.risk_manager.update_balance(self.user_id, balance)
                    
                    logger.info(f"✅ Connected {self.user_id} to {broker_type}, balance: ${balance:.2f}")
                    return True
            
            return False
        
        except Exception as e:
            logger.error(f"Failed to connect {self.user_id} to {broker_type}: {e}")
            
            # Record error in hard controls
            self.hard_controls.record_api_error(self.user_id, 'connection_error')
            
            return False
    
    def can_execute_trade(self, symbol: str, size_usd: float) -> tuple[bool, Optional[str]]:
        """
        Check if user can execute a trade (comprehensive checks).
        
        Args:
            symbol: Trading symbol
            size_usd: Trade size in USD
            
        Returns:
            (can_trade, reason)
        """
        # Check hard controls (kill switches)
        can_trade, reason = self.hard_controls.can_trade(self.user_id)
        if not can_trade:
            return False, f"Hard controls: {reason}"
        
        # Check risk manager (position size, daily limits, etc.)
        can_trade, reason = self.risk_manager.can_trade(self.user_id, size_usd)
        if not can_trade:
            return False, f"Risk limits: {reason}"
        
        # All checks passed
        return True, None
    
    def execute_entry(self, symbol: str, side: str, size_usd: float) -> Optional[Dict]:
        """
        Execute trade entry with full integration.
        
        Args:
            symbol: Trading symbol
            side: 'buy' or 'sell'
            size_usd: Position size in USD
            
        Returns:
            dict: Order result or None if failed
        """
        # Pre-trade checks
        can_trade, reason = self.can_execute_trade(symbol, size_usd)
        if not can_trade:
            logger.warning(f"❌ Cannot execute trade for {self.user_id}: {reason}")
            return None
        
        try:
            # Execute order via broker
            order = self.broker.place_market_order(
                symbol=symbol,
                side=side,
                quantity=size_usd,
                size_type='quote'
            )
            
            # Extract order details
            price = order.get('price', 0.0)
            quantity = order.get('quantity', 0.0)
            
            # Record in PnL tracker
            self.pnl_tracker.record_trade(
                user_id=self.user_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=price,
                size_usd=size_usd,
                strategy='APEX_v7.1',
                broker='kraken'
            )
            
            # Send webhook notification
            self.webhook_notifier.notify_trade_entry(
                user_id=self.user_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=price,
                size_usd=size_usd,
                strategy='APEX_v7.1',
                broker='kraken'
            )
            
            logger.info(f"✅ Entry executed for {self.user_id}: {side} {symbol} ${size_usd:.2f}")
            
            return order
        
        except Exception as e:
            logger.error(f"Failed to execute entry for {self.user_id}: {e}")
            
            # Record error
            self.hard_controls.record_api_error(self.user_id, 'trade_execution_error')
            
            # Send error notification
            self.webhook_notifier.notify_error(
                user_id=self.user_id,
                error_message=str(e),
                symbol=symbol
            )
            
            return None
    
    def execute_exit(
        self,
        symbol: str,
        quantity: float,
        entry_price: float,
        current_price: float
    ) -> Optional[Dict]:
        """
        Execute trade exit with PnL tracking.
        
        Args:
            symbol: Trading symbol
            quantity: Quantity to exit
            entry_price: Original entry price
            current_price: Current exit price
            
        Returns:
            dict: Order result or None if failed
        """
        try:
            # Calculate PnL
            size_usd = quantity * current_price
            pnl_usd = (current_price - entry_price) * quantity
            pnl_pct = ((current_price - entry_price) / entry_price) * 100
            
            # Execute order
            order = self.broker.place_market_order(
                symbol=symbol,
                side='sell',
                quantity=quantity,
                size_type='base'
            )
            
            # Record in PnL tracker with PnL
            self.pnl_tracker.record_trade(
                user_id=self.user_id,
                symbol=symbol,
                side='sell',
                quantity=quantity,
                price=current_price,
                size_usd=size_usd,
                pnl_usd=pnl_usd,
                pnl_pct=pnl_pct,
                strategy='APEX_v7.1',
                broker='kraken'
            )
            
            # Update risk manager
            self.risk_manager.record_trade(self.user_id, pnl_usd)
            
            # Update balance
            balance = self.broker.get_account_balance()
            self.risk_manager.update_balance(self.user_id, balance)
            
            # Send webhook notification
            self.webhook_notifier.notify_trade_exit(
                user_id=self.user_id,
                symbol=symbol,
                side='sell',
                quantity=quantity,
                price=current_price,
                size_usd=size_usd,
                pnl_usd=pnl_usd,
                pnl_pct=pnl_pct,
                strategy='APEX_v7.1',
                broker='kraken'
            )
            
            logger.info(
                f"✅ Exit executed for {self.user_id}: "
                f"{symbol} PnL: ${pnl_usd:+.2f} ({pnl_pct:+.2f}%)"
            )
            
            return order
        
        except Exception as e:
            logger.error(f"Failed to execute exit for {self.user_id}: {e}")
            
            # Record error
            self.hard_controls.record_api_error(self.user_id, 'trade_execution_error')
            
            return None
    
    def get_performance_summary(self) -> Dict:
        """
        Get comprehensive performance summary for user.
        
        Returns:
            dict: Performance metrics
        """
        # Get PnL stats
        pnl_stats = self.pnl_tracker.get_stats(self.user_id)
        
        # Get risk state
        risk_state = self.risk_manager.get_state(self.user_id)
        
        # Get nonce stats
        nonce_stats = self.nonce_manager.get_stats(self.user_id)
        
        # Check trading status
        can_trade, reason = self.can_execute_trade('BTC-USD', 10.0)
        
        return {
            'user_id': self.user_id,
            'can_trade': can_trade,
            'status': reason if not can_trade else 'active',
            'pnl': {
                'total': pnl_stats.get('total_pnl', 0.0),
                'daily': pnl_stats.get('daily_pnl', 0.0),
                'weekly': pnl_stats.get('weekly_pnl', 0.0),
                'monthly': pnl_stats.get('monthly_pnl', 0.0),
                'win_rate': pnl_stats.get('win_rate', 0.0),
                'total_trades': pnl_stats.get('completed_trades', 0)
            },
            'risk': {
                'balance': risk_state.balance,
                'daily_trades': risk_state.daily_trades,
                'daily_pnl': risk_state.daily_pnl,
                'drawdown_pct': risk_state.current_drawdown_pct,
                'circuit_breaker': risk_state.circuit_breaker_triggered
            },
            'nonce': {
                'error_count': nonce_stats.get('error_count', 0),
                'has_errors': nonce_stats.get('has_errors', False)
            }
        }


def example_usage():
    """Example of using the enhanced trading manager."""
    
    # Initialize for a user
    user_id = 'alice'
    manager = EnhancedUserTradingManager(user_id)
    
    # Configure webhook
    manager.webhook_notifier.configure_webhook(
        user_id=user_id,
        webhook_url='https://your-webhook-url.com/notify',
        enabled=True
    )
    
    # Configure risk limits
    manager.risk_manager.update_limits(
        user_id=user_id,
        max_daily_loss_usd=100.0,
        max_position_pct=0.05  # 5% max position
    )
    
    # Connect to broker
    if manager.connect_broker('kraken'):
        # Execute entry
        order = manager.execute_entry(
            symbol='BTC-USD',
            side='buy',
            size_usd=50.0
        )
        
        if order:
            # Later, execute exit
            manager.execute_exit(
                symbol='BTC-USD',
                quantity=0.001,
                entry_price=50000.0,
                current_price=51000.0
            )
    
    # Get performance summary
    summary = manager.get_performance_summary()
    print(f"Performance: {summary}")


if __name__ == '__main__':
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Run example
    example_usage()
