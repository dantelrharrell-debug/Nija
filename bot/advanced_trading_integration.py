"""
NIJA Advanced Trading Integration
Integrates progressive targets, exchange risk profiles, and capital allocation

This module provides a unified interface for:
1. Progressive daily profit target management
2. Exchange-specific risk parameters
3. Multi-exchange capital allocation

Version: 1.0
Author: NIJA Trading Systems
"""

import logging
from typing import Dict, Optional, Tuple
from datetime import datetime, date

from progressive_target_manager import ProgressiveTargetManager, get_progressive_target_manager
from exchange_risk_profiles import ExchangeType, ExchangeRiskManager, get_exchange_risk_manager
from multi_exchange_capital_allocator import MultiExchangeCapitalAllocator, get_capital_allocator

logger = logging.getLogger("nija.advanced_integration")


def validate_configuration(total_capital: float, allocation_strategy: str) -> Tuple[bool, str]:
    """
    Validate configuration for advanced trading features.
    
    Args:
        total_capital: Total capital to validate
        allocation_strategy: Allocation strategy to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    # Validate capital
    if total_capital <= 0:
        return False, f"Invalid total capital: ${total_capital:.2f} (must be > 0)"
    
    if total_capital < 10:
        logger.warning(f"⚠️ Very low capital: ${total_capital:.2f} - trading may be unprofitable due to fees")
    
    # Validate allocation strategy
    valid_strategies = ['conservative', 'risk_adjusted', 'equal_weight']
    if allocation_strategy not in valid_strategies:
        return False, f"Invalid allocation strategy: {allocation_strategy} (must be one of {valid_strategies})"
    
    return True, ""


class AdvancedTradingManager:
    """
    Unified manager for advanced trading features
    
    Coordinates:
    - Progressive profit targets
    - Exchange-specific risk management
    - Multi-exchange capital allocation
    """
    
    def __init__(self, total_capital: float, allocation_strategy: str = "conservative"):
        """
        Initialize Advanced Trading Manager
        
        Args:
            total_capital: Total capital across all exchanges
            allocation_strategy: Capital allocation strategy
            
        Raises:
            ValueError: If configuration is invalid
        """
        # Validate configuration
        is_valid, error_msg = validate_configuration(total_capital, allocation_strategy)
        if not is_valid:
            raise ValueError(f"Invalid configuration: {error_msg}")
        
        # Initialize sub-managers
        self.target_manager = get_progressive_target_manager()
        self.risk_manager = get_exchange_risk_manager()
        self.capital_allocator = get_capital_allocator(total_capital, allocation_strategy)
        
        logger.info("=" * 70)
        logger.info("🚀 Advanced Trading Manager Initialized")
        logger.info("=" * 70)
        logger.info(f"Total Capital: ${total_capital:.2f}")
        logger.info(f"Daily Target: ${self.target_manager.get_current_target():.2f}")
        logger.info(f"Allocation Strategy: {allocation_strategy}")
        logger.info("=" * 70)
    
    def get_position_size_for_trade(self, exchange: ExchangeType, 
                                    base_position_pct: float,
                                    signal_strength: float = 1.0) -> float:
        """
        Calculate optimal position size for a trade
        
        Considers:
        - Exchange-specific risk profile
        - Capital allocation limits
        - Progressive target level
        - Signal strength
        
        Args:
            exchange: Exchange where trade will execute
            base_position_pct: Base position size as %
            signal_strength: Signal quality (0-1)
            
        Returns:
            Position size in USD
        """
        # Get progressive target multiplier
        target_multiplier = self.target_manager.get_position_size_multiplier()
        
        # Adjust base position by signal strength
        adjusted_pct = base_position_pct * signal_strength
        
        # Apply target progression multiplier
        adjusted_pct *= target_multiplier
        
        # Get exchange-optimal position size
        position_size = self.capital_allocator.get_optimal_position_size(
            exchange, adjusted_pct
        )
        
        logger.debug(f"Position sizing: base={base_position_pct*100:.1f}%, "
                    f"signal={signal_strength:.2f}, "
                    f"target_mult={target_multiplier:.2f}x, "
                    f"final=${position_size:.2f}")
        
        return position_size
    
    def get_stop_loss_for_trade(self, exchange: ExchangeType,
                                base_stop_pct: float) -> float:
        """
        Get exchange-adjusted stop-loss percentage
        
        Args:
            exchange: Exchange type
            base_stop_pct: Base stop-loss %
            
        Returns:
            Adjusted stop-loss % as decimal
        """
        return self.risk_manager.get_optimal_stop_loss(exchange, base_stop_pct)
    
    def get_take_profit_targets(self, exchange: ExchangeType) -> Dict[str, float]:
        """
        Get exchange-specific take-profit targets
        
        Args:
            exchange: Exchange type
            
        Returns:
            Dictionary with tp1, tp2, tp3 percentages
        """
        profile = self.risk_manager.get_profile(exchange)
        return {
            'tp1': profile.tp1_target_pct,
            'tp2': profile.tp2_target_pct,
            'tp3': profile.tp3_target_pct,
            'min_target': profile.min_take_profit_pct
        }
    
    def record_completed_trade(self, exchange: ExchangeType, 
                              profit_usd: float,
                              is_win: bool,
                              trading_date: Optional[date] = None):
        """
        Record a completed trade across all tracking systems
        
        Args:
            exchange: Exchange where trade occurred
            profit_usd: Profit/loss in USD
            is_win: True if profitable
            trading_date: Date of trade
        """
        # Record in capital allocator
        self.capital_allocator.record_trade(exchange, profit_usd, is_win)
        
        # Check if we should record daily profit (end of day)
        if trading_date is None:
            trading_date = date.today()
        
        # Get total daily profit so far
        daily_profit = self._calculate_daily_profit(trading_date)
        
        logger.info(f"Trade recorded: {exchange.value} | "
                   f"P&L: ${profit_usd:.2f} | "
                   f"Daily total: ${daily_profit:.2f}")
    
    def _calculate_daily_profit(self, trading_date: date) -> float:
        """Calculate total profit for a specific date"""
        # Sum P&L from all exchanges for the day
        # This is simplified - in production, would track per-day per-exchange
        total_daily = sum(
            alloc.total_pnl_usd 
            for alloc in self.capital_allocator.allocations.values()
        )
        return total_daily
    
    def end_of_day_processing(self, trading_date: Optional[date] = None):
        """
        Run end-of-day processing
        
        - Record daily profit for target tracking
        - Check for target advancement
        - Generate performance reports
        
        Args:
            trading_date: Date to process (defaults to today)
        """
        if trading_date is None:
            trading_date = date.today()
        
        # Calculate total daily profit
        daily_profit = self._calculate_daily_profit(trading_date)
        
        # Record in progressive target manager
        target_achieved = self.target_manager.record_daily_profit(
            daily_profit, trading_date
        )
        
        # Generate reports
        logger.info("\n" + "=" * 70)
        logger.info("📊 END OF DAY REPORT")
        logger.info("=" * 70)
        logger.info(f"Date: {trading_date}")
        logger.info(f"Daily Profit: ${daily_profit:.2f}")
        logger.info(f"Target: ${self.target_manager.get_current_target():.2f}")
        logger.info(f"Target Achieved: {'✅ YES' if target_achieved else '❌ NO'}")
        logger.info("=" * 70)
        
        # Check if rebalancing needed
        needs_rebalance, reason = self.capital_allocator.check_rebalancing_needed()
        if needs_rebalance:
            logger.warning(f"⚠️ Rebalancing recommended: {reason}")
    
    def update_exchange_balance(self, exchange: ExchangeType,
                               available_balance: float,
                               in_positions: float):
        """
        Update balance information for an exchange
        
        Args:
            exchange: Exchange type
            available_balance: Available USD
            in_positions: USD in open positions
        """
        self.capital_allocator.update_balance(
            exchange, available_balance, in_positions
        )
    
    def get_trading_limits_for_exchange(self, exchange: ExchangeType) -> Dict:
        """
        Get all trading limits and parameters for an exchange
        
        Args:
            exchange: Exchange type
            
        Returns:
            Dictionary with limits and parameters
        """
        profile = self.risk_manager.get_profile(exchange)
        allocation = self.capital_allocator.get_allocation(exchange)
        
        return {
            'exchange': exchange.value,
            'max_trades_per_day': profile.max_trades_per_day,
            'max_open_positions': profile.max_open_positions,
            'max_position_size_usd': allocation.allocated_capital_usd * profile.max_position_size_pct if allocation else 0,
            'min_position_size_usd': profile.min_position_size_usd,
            'max_total_exposure_pct': profile.max_total_exposure_pct,
            'allocated_capital': allocation.allocated_capital_usd if allocation else 0,
            'available_balance': allocation.available_balance_usd if allocation else 0,
        }
    
    def can_trade_on_exchange(self, exchange: ExchangeType,
                             position_size_usd: float) -> Tuple[bool, str]:
        """
        Check if we can execute a trade on an exchange
        
        Args:
            exchange: Exchange type
            position_size_usd: Desired position size
            
        Returns:
            Tuple of (can_trade, reason)
        """
        allocation = self.capital_allocator.get_allocation(exchange)
        if not allocation:
            return False, f"No allocation for {exchange.value}"
        
        # Check if enough balance
        if position_size_usd > allocation.available_balance_usd:
            return False, f"Insufficient balance: ${allocation.available_balance_usd:.2f} < ${position_size_usd:.2f}"
        
        # Check exposure limits
        profile = self.risk_manager.get_profile(exchange)
        max_exposure = allocation.allocated_capital_usd * profile.max_total_exposure_pct
        current_exposure = allocation.in_positions_usd
        
        if (current_exposure + position_size_usd) > max_exposure:
            return False, f"Would exceed max exposure: ${max_exposure:.2f}"
        
        return True, "OK to trade"
    
    def print_status_report(self):
        """Print comprehensive status report"""
        print("\n" + "=" * 90)
        print("🎯 NIJA ADVANCED TRADING STATUS REPORT")
        print("=" * 90)
        
        # Progressive targets
        stats = self.target_manager.get_target_statistics()
        print(f"\n📊 Progressive Profit Targets:")
        print(f"   Current Target: ${stats['current_target']:.2f}/day")
        print(f"   Progress to $1000/day Goal: {stats['progress_percentage']:.1f}%")
        print(f"   Levels Completed: {stats['levels_completed']}/{stats['total_levels']}")
        print(f"   Recent Average: ${stats['avg_recent_profit']:.2f}/day")
        
        # Capital allocation
        print(f"\n💰 Multi-Exchange Capital Allocation:")
        for exchange, alloc in self.capital_allocator.allocations.items():
            print(f"   {exchange.value:12s}: ${alloc.allocated_capital_usd:8.2f} "
                  f"({alloc.current_allocation_pct:5.1f}%) | "
                  f"P&L: ${alloc.total_pnl_usd:7.2f} | "
                  f"Trades: {alloc.total_trades:3d}")
        
        # Overall performance
        total_pnl = sum(a.total_pnl_usd for a in self.capital_allocator.allocations.values())
        print(f"\n📈 Overall Performance:")
        print(f"   Total Capital: ${self.capital_allocator.total_capital_usd:.2f}")
        print(f"   Total P&L: ${total_pnl:.2f}")
        print(f"   ROI: {(total_pnl/self.capital_allocator.total_capital_usd)*100:.2f}%")
        
        print("=" * 90 + "\n")


# Singleton instance
_advanced_manager_instance: Optional[AdvancedTradingManager] = None


def get_advanced_trading_manager(total_capital: Optional[float] = None,
                                 allocation_strategy: str = "conservative") -> AdvancedTradingManager:
    """
    Get singleton instance of AdvancedTradingManager
    
    Args:
        total_capital: Total capital (required on first call)
        allocation_strategy: Allocation strategy
        
    Returns:
        AdvancedTradingManager instance
    """
    global _advanced_manager_instance
    
    if _advanced_manager_instance is None:
        if total_capital is None:
            raise ValueError("total_capital required for first initialization")
        _advanced_manager_instance = AdvancedTradingManager(total_capital, allocation_strategy)
    
    return _advanced_manager_instance


if __name__ == "__main__":
    # Test/demonstration
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s - %(message)s'
    )
    
    # Initialize with $1000 capital
    manager = AdvancedTradingManager(1000.0, "conservative")
    
    # Simulate a trade on Coinbase
    print("\nSimulating trade on Coinbase...")
    pos_size = manager.get_position_size_for_trade(
        ExchangeType.COINBASE, 
        base_position_pct=0.05,
        signal_strength=0.9
    )
    print(f"Position size: ${pos_size:.2f}")
    
    # Get trading limits
    limits = manager.get_trading_limits_for_exchange(ExchangeType.COINBASE)
    print(f"\nCoinbase trading limits:")
    for key, value in limits.items():
        print(f"  {key}: {value}")
    
    # Print full status
    manager.print_status_report()
