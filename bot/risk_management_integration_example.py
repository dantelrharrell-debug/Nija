"""
NIJA Risk Management Integration Example
=========================================

Demonstrates how to use all 7 risk management features together
in a complete order validation and execution flow.

Author: NIJA Trading Systems
Date: February 8, 2026
"""

import logging
from typing import Tuple, Optional, Dict, Any

# Import risk management modules
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from minimum_notional_guard import get_notional_guard, should_block_order
from validators.fee_validator import FeeValidator
from capital_reservation_manager import (
    get_capital_reservation_manager,
    reserve_capital,
    release_capital,
    can_open_position
)
from kill_switch import get_kill_switch, get_auto_trigger
from reconciliation_watchdog import get_reconciliation_watchdog
from user_pnl_tracker import get_user_pnl_tracker
from monitoring_system import MonitoringSystem, AlertType, AlertLevel

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class RiskManagedTradingEngine:
    """
    Trading engine with full risk management integration.
    
    Implements all 7 features:
    1. Minimum Notional Guard
    2. Fee-Aware Position Sizing
    3. Capital Reservation
    4. Kill Switch Auto-Triggers
    5. Reconciliation Watchdog
    6. Per-User Performance Attribution
    7. High Signal-to-Noise Alerting
    """
    
    def __init__(
        self,
        user_id: str = "default",
        broker: str = "coinbase",
        enable_auto_triggers: bool = True
    ):
        """
        Initialize risk-managed trading engine.
        
        Args:
            user_id: User identifier
            broker: Broker name
            enable_auto_triggers: Enable kill switch auto-triggers
        """
        self.user_id = user_id
        self.broker = broker
        
        # Initialize components
        self.notional_guard = get_notional_guard(
            min_notional_usd=5.0,
            strict_mode=True
        )
        self.fee_validator = FeeValidator()
        self.capital_manager = get_capital_reservation_manager(
            safety_buffer_pct=0.20,
            min_free_capital_usd=5.0
        )
        self.kill_switch = get_kill_switch()
        self.auto_trigger = get_auto_trigger(
            max_daily_loss_pct=10.0,
            max_consecutive_losses=5,
            enable_auto_trigger=enable_auto_triggers
        )
        self.watchdog = get_reconciliation_watchdog(
            enable_auto_actions=False
        )
        self.pnl_tracker = get_user_pnl_tracker()
        self.monitor = MonitoringSystem()
        
        logger.info(
            f"✅ Risk-Managed Trading Engine initialized for {user_id} on {broker}"
        )
    
    def validate_order(
        self,
        symbol: str,
        size: float,
        price: float,
        balance: float
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Complete order validation using all risk management features.
        
        Args:
            symbol: Trading symbol
            size: Order size in base currency
            price: Order price
            balance: Account balance
        
        Returns:
            Tuple of (is_valid, message, details)
        """
        details = {
            'symbol': symbol,
            'size': size,
            'price': price,
            'order_value': size * price,
            'balance': balance,
            'checks_passed': [],
            'checks_failed': []
        }
        
        # ===== CHECK 1: Kill Switch =====
        if self.kill_switch.is_active():
            details['checks_failed'].append('kill_switch')
            return False, "🚨 Kill switch active - no new entries allowed", details
        details['checks_passed'].append('kill_switch')
        
        # ===== CHECK 2: Minimum Notional =====
        is_valid, error, notional_details = self.notional_guard.validate_order_notional(
            size=size,
            price=price,
            exchange=self.broker,
            balance=balance,
            symbol=symbol
        )
        
        if not is_valid:
            details['checks_failed'].append('minimum_notional')
            details['notional_details'] = notional_details
            return False, f"❌ {error}", details
        details['checks_passed'].append('minimum_notional')
        details['notional_details'] = notional_details
        
        # ===== CHECK 3: Fee-to-Position Ratio =====
        try:
            from validation_models import ValidationLevel
        except ImportError:
            # Fallback if validation_models not available
            class ValidationLevel:
                ERROR = "ERROR"
                WARNING = "WARNING"
                PASS = "PASS"
        
        fee_result = self.fee_validator.validate_fee_to_position_ratio(
            position_size=size,
            entry_price=price,
            broker=self.broker,
            max_fee_pct=2.0,
            symbol=symbol,
            account_id=self.user_id
        )
        
        if fee_result.level == ValidationLevel.ERROR:
            details['checks_failed'].append('fee_ratio')
            details['fee_details'] = fee_result.metrics
            return False, f"❌ {fee_result.message}", details
        details['checks_passed'].append('fee_ratio')
        details['fee_details'] = fee_result.metrics
        
        # ===== CHECK 4: Capital Reservation =====
        order_value = size * price
        can_open, msg, cap_details = can_open_position(
            total_balance=balance,
            new_position_size=order_value,
            account_id=self.user_id
        )
        
        if not can_open:
            details['checks_failed'].append('capital_reservation')
            details['capital_details'] = cap_details
            return False, f"❌ {msg}", details
        details['checks_passed'].append('capital_reservation')
        details['capital_details'] = cap_details
        
        # All checks passed
        return True, "✅ Order validation passed", details
    
    def execute_entry(
        self,
        symbol: str,
        size: float,
        price: float,
        balance: float
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Execute entry order with risk management.
        
        Args:
            symbol: Trading symbol
            size: Order size
            price: Entry price
            balance: Account balance
        
        Returns:
            Tuple of (success, message, position_id)
        """
        # Validate order
        is_valid, msg, details = self.validate_order(symbol, size, price, balance)
        
        if not is_valid:
            logger.error(f"Order validation failed: {msg}")
            return False, msg, None
        
        # Reserve capital
        position_id = f"{self.user_id}_{symbol}_{int(price)}_{int(size * 1000)}"
        order_value = size * price
        
        reserved = reserve_capital(
            position_id=position_id,
            amount=order_value,
            symbol=symbol,
            account_id=self.user_id,
            broker=self.broker
        )
        
        if not reserved:
            return False, "Failed to reserve capital", None
        
        # Record entry trade
        self.pnl_tracker.record_trade(
            user_id=self.user_id,
            symbol=symbol,
            side="buy",
            quantity=size,
            price=price,
            size_usd=order_value,
            broker=self.broker
        )
        
        logger.info(
            f"✅ Entry executed: {symbol} {size} @ ${price:.2f} "
            f"(${order_value:.2f}) - Position ID: {position_id}"
        )
        
        return True, "Entry successful", position_id
    
    def execute_exit(
        self,
        position_id: str,
        symbol: str,
        size: float,
        entry_price: float,
        exit_price: float,
        balance: float
    ) -> Tuple[bool, str, Dict]:
        """
        Execute exit order with P&L tracking.
        
        Args:
            position_id: Position identifier
            symbol: Trading symbol
            size: Position size
            entry_price: Entry price
            exit_price: Exit price
            balance: Current account balance
        
        Returns:
            Tuple of (success, message, pnl_details)
        """
        # Calculate P&L
        order_value = size * exit_price
        gross_pnl = (exit_price - entry_price) * size
        
        # Calculate fees
        total_fees = self.fee_validator.calculate_total_fees(
            entry_size=size,
            entry_price=entry_price,
            exit_price=exit_price,
            broker=self.broker
        )
        
        net_pnl = gross_pnl - total_fees
        pnl_pct = (net_pnl / (size * entry_price)) * 100
        
        # Record exit trade
        entry_time = None  # Would be retrieved from position tracker
        exit_time = None   # Current time
        
        self.pnl_tracker.record_trade(
            user_id=self.user_id,
            symbol=symbol,
            side="sell",
            quantity=size,
            price=exit_price,
            size_usd=order_value,
            pnl_usd=net_pnl,
            pnl_pct=pnl_pct,
            broker=self.broker,
            fee_usd=total_fees
        )
        
        # Release capital
        released = release_capital(position_id)
        
        # Check auto-triggers
        is_winner = net_pnl > 0
        triggered = self.auto_trigger.auto_trigger_if_needed(
            current_balance=balance,
            last_trade_result=is_winner
        )
        
        if triggered:
            # Log critical alert (monitoring system doesn't have trigger_alert method yet)
            logger.critical(
                f"🚨 KILL_SWITCH_ACTIVATED: Auto-trigger activated - "
                f"Balance: ${balance:.2f}, P&L: ${net_pnl:.2f}"
            )
        
        pnl_details = {
            'gross_pnl': gross_pnl,
            'fees': total_fees,
            'net_pnl': net_pnl,
            'pnl_pct': pnl_pct,
            'released_capital': released
        }
        
        logger.info(
            f"✅ Exit executed: {symbol} {size} @ ${exit_price:.2f} "
            f"| Net P&L: ${net_pnl:+.2f} ({pnl_pct:+.2f}%) "
            f"| Fees: ${total_fees:.2f}"
        )
        
        return True, "Exit successful", pnl_details
    
    def reconcile_positions(
        self,
        exchange_balances: Dict[str, float],
        internal_positions: Dict[str, float],
        prices: Dict[str, float]
    ) -> int:
        """
        Reconcile positions with exchange.
        
        Args:
            exchange_balances: Balances from exchange
            internal_positions: Internal position tracker
            prices: Current prices
        
        Returns:
            Number of discrepancies found
        """
        if not self.watchdog.should_reconcile():
            logger.debug("Skipping reconciliation - too soon")
            return 0
        
        discrepancies = self.watchdog.reconcile_balances(
            exchange_balances=exchange_balances,
            internal_positions=internal_positions,
            prices=prices,
            account_id=self.user_id,
            broker=self.broker
        )
        
        if discrepancies:
            # Log alert (monitoring system doesn't have trigger_alert method yet)
            logger.warning(
                f"⚠️ RECONCILIATION_ISSUE: Found {len(discrepancies)} discrepancies"
            )
        
        return len(discrepancies)
    
    def get_performance_summary(self) -> Dict:
        """Get user performance summary"""
        stats = self.pnl_tracker.get_stats(self.user_id)
        
        # Add capital reservation info
        cap_summary = self.capital_manager.get_reservation_summary()
        stats['capital_reserved'] = cap_summary.get('total_reserved', 0.0)
        stats['open_positions_count'] = cap_summary.get('open_positions', 0)
        
        # Add kill switch status
        stats['kill_switch_active'] = self.kill_switch.is_active()
        
        return stats


# ===== EXAMPLE USAGE =====

def example_trading_flow():
    """Example of complete trading flow with risk management"""
    
    print("\n" + "=" * 60)
    print("NIJA Risk-Managed Trading Flow Example")
    print("=" * 60 + "\n")
    
    # Initialize engine
    engine = RiskManagedTradingEngine(
        user_id="trader_001",
        broker="coinbase",
        enable_auto_triggers=True
    )
    
    # Starting balance
    balance = 100.0
    print(f"Starting Balance: ${balance:.2f}\n")
    
    # ===== TRADE 1: Successful Entry =====
    print("--- Trade 1: Enter BTC Position ---")
    success, msg, pos_id = engine.execute_entry(
        symbol="BTC-USD",
        size=0.001,
        price=50000.0,
        balance=balance
    )
    print(f"Result: {msg}")
    if success:
        print(f"Position ID: {pos_id}\n")
    
    # ===== TRADE 2: Failed Entry (below minimum) =====
    print("--- Trade 2: Try Small Position (Should Fail) ---")
    success, msg, pos_id = engine.execute_entry(
        symbol="ETH-USD",
        size=0.0001,
        price=3000.0,
        balance=balance
    )
    print(f"Result: {msg}\n")
    
    # ===== TRADE 3: Exit Position =====
    print("--- Trade 3: Exit BTC Position ---")
    balance = 102.0  # Assume price moved up
    success, msg, pnl = engine.execute_exit(
        position_id=pos_id,
        symbol="BTC-USD",
        size=0.001,
        entry_price=50000.0,
        exit_price=52000.0,
        balance=balance
    )
    print(f"Result: {msg}")
    if success:
        print(f"P&L Details: {pnl}\n")
    
    # ===== RECONCILIATION =====
    print("--- Reconciliation Check ---")
    discrepancies = engine.reconcile_positions(
        exchange_balances={'BTC': 0.0, 'USD': 102.0},
        internal_positions={},
        prices={'BTC': 52000.0, 'USD': 1.0}
    )
    print(f"Discrepancies found: {discrepancies}\n")
    
    # ===== PERFORMANCE SUMMARY =====
    print("--- Performance Summary ---")
    summary = engine.get_performance_summary()
    print(f"Total Trades: {summary['total_trades']}")
    print(f"Win Rate: {summary['win_rate']:.1f}%")
    print(f"Net P&L: ${summary.get('net_pnl_after_fees', 0):.2f}")
    print(f"Total Fees: ${summary['total_fees']:.2f}")
    print(f"Kill Switch Active: {summary['kill_switch_active']}")
    
    print("\n" + "=" * 60)
    print("Example Complete!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    example_trading_flow()
