"""
NIJA Live Tracker Integration
==============================

Integration module to automatically track live trades in the execution engine.

This module provides hooks that can be added to execution_engine.py to automatically
record all trades in the LiveExecutionTracker for performance monitoring.

Usage:
    from bot.live_tracker_integration import LiveTrackerIntegration

    # In execution_engine.py __init__:
    self.live_tracker_integration = LiveTrackerIntegration(
        initial_balance=10000.0,
        enabled=True
    )

    # After successful entry execution:
    self.live_tracker_integration.record_entry(
        trade_id=position_id,
        symbol=symbol,
        side=side,
        entry_price=final_entry_price,
        size=quantity,
        stop_loss=stop_loss,
        take_profit=take_profit_levels.get('tp1'),
        commission=entry_fee,
        broker=broker_name
    )

    # After successful exit execution:
    self.live_tracker_integration.record_exit(
        trade_id=position_id,
        exit_price=exit_price,
        exit_reason=reason,
        commission=exit_fee
    )

Author: NIJA Trading Systems
Date: January 28, 2026
"""

import logging
import os
from typing import Optional
from pathlib import Path

logger = logging.getLogger("nija.live_tracker_integration")


class LiveTrackerIntegration:
    """
    Integration layer for live execution tracking
    """

    def __init__(
        self,
        initial_balance: float,
        data_dir: Optional[str] = None,
        enabled: bool = True,
        max_daily_loss_pct: float = 5.0,
        max_drawdown_pct: float = 12.0
    ):
        """
        Initialize live tracker integration

        Args:
            initial_balance: Starting account balance
            data_dir: Data directory (default: ./data/live_tracking)
            enabled: Enable tracking (can be disabled for testing)
            max_daily_loss_pct: Maximum daily loss % for circuit breaker
            max_drawdown_pct: Maximum drawdown % for alerts
        """
        self.enabled = enabled
        self.tracker = None

        if not enabled:
            logger.info("Live tracker integration disabled")
            return

        # Set default data directory
        if data_dir is None:
            data_dir = os.getenv('LIVE_TRACKER_DATA_DIR', './data/live_tracking')

        try:
            # Import here to avoid circular dependencies
            from bot.live_execution_tracker import LiveExecutionTracker

            self.tracker = LiveExecutionTracker(
                initial_balance=initial_balance,
                data_dir=data_dir,
                max_daily_loss_pct=max_daily_loss_pct,
                max_drawdown_pct=max_drawdown_pct,
                enable_alerts=True
            )

            logger.info("✅ Live tracker integration initialized")
            logger.info(f"   Data directory: {data_dir}")
            logger.info(f"   Risk limits: Daily loss={max_daily_loss_pct}%, Max DD={max_drawdown_pct}%")

        except Exception as e:
            logger.error(f"Failed to initialize live tracker: {e}")
            logger.warning("Live tracking will be disabled")
            self.enabled = False

    def record_entry(
        self,
        trade_id: str,
        symbol: str,
        side: str,
        entry_price: float,
        size: float,
        stop_loss: float,
        take_profit: Optional[float] = None,
        commission: float = 0.0,
        broker: str = "coinbase",
        account_id: str = "platform",
        entry_score: Optional[float] = None,
        slippage: Optional[float] = None
    ):
        """
        Record trade entry

        This should be called after a successful entry order execution.

        Args:
            trade_id: Unique trade identifier (position_id)
            symbol: Trading symbol
            side: 'long' or 'short'
            entry_price: Actual entry price (fill price)
            size: Position size in base asset
            stop_loss: Stop loss price
            take_profit: Take profit price (optional)
            commission: Commission paid on entry
            broker: Broker name (coinbase, kraken, etc.)
            account_id: Account identifier
            entry_score: Entry quality score (optional)
            slippage: Slippage experienced (optional)
        """
        if not self.enabled or self.tracker is None:
            return

        try:
            self.tracker.record_entry(
                trade_id=trade_id,
                symbol=symbol,
                side=side,
                entry_price=entry_price,
                size=size,
                stop_loss=stop_loss,
                take_profit=take_profit,
                broker=broker,
                account_id=account_id,
                entry_score=entry_score,
                commission=commission,
                slippage=slippage
            )
        except Exception as e:
            logger.error(f"Failed to record entry: {e}")

    def record_exit(
        self,
        trade_id: str,
        exit_price: float,
        exit_reason: str = "manual",
        commission: float = 0.0,
        slippage: Optional[float] = None
    ):
        """
        Record trade exit

        This should be called after a successful exit order execution.

        Args:
            trade_id: Trade identifier (position_id)
            exit_price: Actual exit price (fill price)
            exit_reason: Reason for exit (stop_loss, take_profit, manual, etc.)
            commission: Commission paid on exit
            slippage: Slippage experienced (optional)
        """
        if not self.enabled or self.tracker is None:
            return

        try:
            self.tracker.record_exit(
                trade_id=trade_id,
                exit_price=exit_price,
                exit_reason=exit_reason,
                commission=commission,
                slippage=slippage
            )
        except Exception as e:
            logger.error(f"Failed to record exit: {e}")

    def update_position(
        self,
        trade_id: str,
        current_price: float
    ):
        """
        Update open position with current price (for unrealized P&L)

        Args:
            trade_id: Trade identifier
            current_price: Current market price
        """
        if not self.enabled or self.tracker is None:
            return

        try:
            self.tracker.update_position(trade_id, current_price)
        except Exception as e:
            logger.error(f"Failed to update position: {e}")

    def get_performance_snapshot(self, current_balance: float):
        """
        Get current performance snapshot

        Args:
            current_balance: Current account balance

        Returns:
            LivePerformanceSnapshot or None
        """
        if not self.enabled or self.tracker is None:
            return None

        try:
            return self.tracker.get_performance_snapshot(current_balance)
        except Exception as e:
            logger.error(f"Failed to get performance snapshot: {e}")
            return None

    def print_daily_summary(self):
        """Print daily trading summary"""
        if not self.enabled or self.tracker is None:
            return

        try:
            self.tracker.print_daily_summary()
        except Exception as e:
            logger.error(f"Failed to print daily summary: {e}")

    def export_to_csv(self, output_path: Optional[str] = None):
        """
        Export trades to CSV

        Args:
            output_path: Output file path (optional)
        """
        if not self.enabled or self.tracker is None:
            return

        try:
            self.tracker.export_to_csv(output_path)
        except Exception as e:
            logger.error(f"Failed to export to CSV: {e}")


# Convenience function for integration
def create_live_tracker_integration(
    initial_balance: float = None,
    enabled: bool = None
) -> LiveTrackerIntegration:
    """
    Create live tracker integration with environment-based configuration

    Environment variables:
        LIVE_TRACKER_ENABLED: Enable live tracking (default: true)
        LIVE_TRACKER_DATA_DIR: Data directory (default: ./data/live_tracking)
        LIVE_TRACKER_MAX_DAILY_LOSS: Max daily loss % (default: 5.0)
        LIVE_TRACKER_MAX_DRAWDOWN: Max drawdown % (default: 12.0)
        INITIAL_BALANCE: Initial account balance (required if not provided)

    Args:
        initial_balance: Override initial balance from environment
        enabled: Override enabled flag from environment

    Returns:
        LiveTrackerIntegration instance
    """
    # Get configuration from environment
    env_enabled = os.getenv('LIVE_TRACKER_ENABLED', 'true').lower() in ['true', '1', 'yes']
    env_balance = float(os.getenv('INITIAL_BALANCE', '10000.0'))
    env_data_dir = os.getenv('LIVE_TRACKER_DATA_DIR', './data/live_tracking')
    env_max_daily_loss = float(os.getenv('LIVE_TRACKER_MAX_DAILY_LOSS', '5.0'))
    env_max_drawdown = float(os.getenv('LIVE_TRACKER_MAX_DRAWDOWN', '12.0'))

    # Override with provided values
    final_enabled = enabled if enabled is not None else env_enabled
    final_balance = initial_balance if initial_balance is not None else env_balance

    return LiveTrackerIntegration(
        initial_balance=final_balance,
        data_dir=env_data_dir,
        enabled=final_enabled,
        max_daily_loss_pct=env_max_daily_loss,
        max_drawdown_pct=env_max_drawdown
    )


# Example integration with execution_engine.py
INTEGRATION_EXAMPLE = """
# ============================================================================
# EXAMPLE: How to integrate with execution_engine.py
# ============================================================================

# 1. Add import at top of execution_engine.py:
from bot.live_tracker_integration import create_live_tracker_integration

# 2. Add to ExecutionEngine.__init__():
def __init__(self, broker_client, user_id="platform", ...):
    # ... existing initialization ...

    # Initialize live tracker integration
    try:
        self.live_tracker = create_live_tracker_integration(
            initial_balance=10000.0,  # or get from account balance
            enabled=True
        )
    except Exception as e:
        logger.warning(f"Live tracker initialization failed: {e}")
        self.live_tracker = None

# 3. In execute_entry(), after successful order execution (around line 447):
# Record entry in live tracker
if self.live_tracker:
    self.live_tracker.record_entry(
        trade_id=position_id,
        symbol=symbol,
        side=side,
        entry_price=final_entry_price,
        size=quantity,
        stop_loss=stop_loss,
        take_profit=take_profit_levels.get('tp1'),
        commission=entry_fee,
        broker=broker_name_str,
        account_id=self.user_id
    )

# 4. In execute_exit(), after successful close (where trade_ledger.record_exit is called):
# Record exit in live tracker
if self.live_tracker:
    self.live_tracker.record_exit(
        trade_id=position.get('position_id'),
        exit_price=exit_price,
        exit_reason=reason,
        commission=exit_fee
    )

# 5. Optional: Add daily summary at end of trading day
if self.live_tracker:
    self.live_tracker.print_daily_summary()
"""

if __name__ == "__main__":
    print("="*80)
    print("NIJA Live Tracker Integration")
    print("="*80)
    print(INTEGRATION_EXAMPLE)
    print("="*80)
