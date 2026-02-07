"""
NIJA Analytics Integration Helper
==================================

Helper functions to integrate trade analytics into the trading strategy
without modifying the core trading logic extensively.

This module provides:
1. Market scan timing wrapper
2. Capital utilization calculator
3. Trade outcome recorder

Author: NIJA Trading Systems
Date: February 7, 2026
"""

import time
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from contextlib import contextmanager

try:
    from bot.trade_analytics import (
        get_analytics, MarketScanMetrics, CapitalUtilization,
        TradeRecord, EntryReason, ExitReason, SignalType
    )
except ImportError:
    from trade_analytics import (
        get_analytics, MarketScanMetrics, CapitalUtilization,
        TradeRecord, EntryReason, ExitReason, SignalType
    )

logger = logging.getLogger("nija.analytics_integration")


class MarketScanTimer:
    """
    Context manager for timing market scans.
    
    Usage:
        with MarketScanTimer(total_markets=732, batch_size=30) as timer:
            # ... scan markets ...
            timer.add_signal()  # Track signals generated
            timer.add_trade()   # Track trades executed
    """
    
    def __init__(self, total_markets: int, batch_size: int, batch_number: int = 0, rotation_enabled: bool = True):
        self.total_markets = total_markets
        self.batch_size = batch_size
        self.batch_number = batch_number
        self.rotation_enabled = rotation_enabled
        
        self.start_time = None
        self.end_time = None
        self.markets_scanned = 0
        self.markets_skipped = 0
        self.api_calls = 0
        self.rate_limit_delays_ms = 0
        self.signals_generated = 0
        self.trades_executed = 0
        
        self.analytics = get_analytics()
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_time = time.time()
        
        # Calculate metrics
        duration_seconds = self.end_time - self.start_time
        avg_time_per_market_ms = (
            (duration_seconds * 1000 / self.markets_scanned)
            if self.markets_scanned > 0 else 0
        )
        
        # Create metrics object
        metrics = MarketScanMetrics(
            scan_id=f"scan_{int(self.start_time)}",
            timestamp_start=datetime.fromtimestamp(self.start_time).isoformat(),
            timestamp_end=datetime.fromtimestamp(self.end_time).isoformat(),
            duration_seconds=duration_seconds,
            total_markets_available=self.total_markets,
            markets_scanned=self.markets_scanned,
            markets_skipped=self.markets_skipped,
            avg_time_per_market_ms=avg_time_per_market_ms,
            total_api_calls=self.api_calls,
            total_rate_limit_delays_ms=self.rate_limit_delays_ms,
            signals_generated=self.signals_generated,
            trades_executed=self.trades_executed,
            batch_size=self.batch_size,
            batch_number=self.batch_number,
            rotation_enabled=self.rotation_enabled
        )
        
        # Log to analytics
        self.analytics.log_market_scan(metrics)
        
        return False  # Don't suppress exceptions
    
    def add_market_scanned(self):
        """Increment markets scanned counter"""
        self.markets_scanned += 1
    
    def add_market_skipped(self):
        """Increment markets skipped counter"""
        self.markets_skipped += 1
    
    def add_api_call(self):
        """Increment API call counter"""
        self.api_calls += 1
    
    def add_rate_limit_delay(self, delay_ms: float):
        """Add rate limit delay time"""
        self.rate_limit_delays_ms += delay_ms
    
    def add_signal(self):
        """Increment signals generated counter"""
        self.signals_generated += 1
    
    def add_trade(self):
        """Increment trades executed counter"""
        self.trades_executed += 1


def calculate_capital_utilization(
    total_capital: float,
    positions: List[Dict],
    broker: Optional[Any] = None
) -> CapitalUtilization:
    """
    Calculate capital utilization metrics from current positions.
    
    Args:
        total_capital: Total capital in USD
        positions: List of position dictionaries
        broker: Broker instance for fetching prices (optional)
    
    Returns:
        CapitalUtilization dataclass
    """
    # Calculate capital in positions
    capital_in_positions = 0.0
    position_sizes = []
    largest_position_usd = 0.0
    smallest_position_usd = float('inf')
    largest_position_symbol = ""
    unrealized_pnl = 0.0
    
    for pos in positions:
        symbol = pos.get('symbol', '')
        quantity = pos.get('quantity', 0)
        
        # Try to get current price
        current_price = pos.get('current_price', 0)
        if current_price == 0 and broker:
            try:
                current_price = broker.get_current_price(symbol)
            except Exception:
                current_price = 0
        
        if current_price > 0:
            position_value = quantity * current_price
            capital_in_positions += position_value
            position_sizes.append(position_value)
            
            if position_value > largest_position_usd:
                largest_position_usd = position_value
                largest_position_symbol = symbol
            
            if position_value < smallest_position_usd:
                smallest_position_usd = position_value
            
            # Calculate unrealized P&L if entry price available
            entry_price = pos.get('entry_price', 0)
            if entry_price > 0:
                pnl = (current_price - entry_price) * quantity
                unrealized_pnl += pnl
    
    # Handle case of no positions
    if not position_sizes:
        smallest_position_usd = 0.0
    
    # Calculate metrics
    idle_capital = max(0, total_capital - capital_in_positions)
    utilization_pct = (capital_in_positions / total_capital * 100) if total_capital > 0 else 0.0
    avg_position_size = (capital_in_positions / len(positions)) if positions else 0.0
    
    return CapitalUtilization(
        timestamp=datetime.now().isoformat(),
        total_capital_usd=total_capital,
        capital_in_positions_usd=capital_in_positions,
        idle_capital_usd=idle_capital,
        utilization_pct=utilization_pct,
        num_positions=len(positions),
        avg_position_size_usd=avg_position_size,
        largest_position_usd=largest_position_usd,
        smallest_position_usd=smallest_position_usd,
        largest_position_symbol=largest_position_symbol,
        unrealized_pnl_usd=unrealized_pnl,
        realized_pnl_today_usd=0.0  # Would need to be tracked separately
    )


def log_capital_utilization(
    total_capital: float,
    positions: List[Dict],
    broker: Optional[Any] = None
):
    """
    Log capital utilization to analytics.
    
    Args:
        total_capital: Total capital in USD
        positions: List of position dictionaries
        broker: Broker instance for fetching prices (optional)
    """
    analytics = get_analytics()
    utilization = calculate_capital_utilization(total_capital, positions, broker)
    analytics.log_capital_utilization(utilization)


def infer_entry_reason(conditions: Dict[str, Any]) -> str:
    """
    Infer entry reason from trading conditions.
    
    Args:
        conditions: Dict with trading signal conditions
            - rsi_9: RSI_9 value
            - rsi_14: RSI_14 value
            - tradingview: TradingView signal
            - heartbeat: Is heartbeat trade
            - manual: Is manual entry
    
    Returns:
        EntryReason enum value as string
    """
    if conditions.get('heartbeat', False):
        return EntryReason.HEARTBEAT_TRADE.value
    
    if conditions.get('manual', False):
        return EntryReason.MANUAL_ENTRY.value
    
    if conditions.get('tradingview'):
        signal = conditions['tradingview']
        if signal.lower() in ['buy', 'long']:
            return EntryReason.TRADINGVIEW_BUY_SIGNAL.value
        elif signal.lower() in ['sell', 'short']:
            return EntryReason.TRADINGVIEW_SELL_SIGNAL.value
    
    rsi_9 = conditions.get('rsi_9')
    rsi_14 = conditions.get('rsi_14')
    rsi_9_oversold_threshold = conditions.get('rsi_9_oversold_threshold', 30)
    rsi_14_oversold_threshold = conditions.get('rsi_14_oversold_threshold', 30)
    
    if rsi_9 is not None and rsi_14 is not None:
        if rsi_9 < rsi_9_oversold_threshold and rsi_14 < rsi_14_oversold_threshold:
            return EntryReason.DUAL_RSI_OVERSOLD.value
        elif rsi_9 < rsi_9_oversold_threshold:
            return EntryReason.RSI_9_OVERSOLD.value
        elif rsi_14 < rsi_14_oversold_threshold:
            return EntryReason.RSI_14_OVERSOLD.value
    
    return EntryReason.UNKNOWN.value


def infer_signal_type(conditions: Dict[str, Any]) -> str:
    """
    Infer signal type for PnL attribution.
    
    Args:
        conditions: Dict with trading signal conditions
    
    Returns:
        SignalType enum value as string
    """
    if conditions.get('heartbeat', False):
        return SignalType.HEARTBEAT.value
    
    if conditions.get('manual', False):
        return SignalType.MANUAL.value
    
    if conditions.get('tradingview'):
        return SignalType.TRADINGVIEW.value
    
    rsi_9 = conditions.get('rsi_9')
    rsi_14 = conditions.get('rsi_14')
    rsi_9_oversold_threshold = conditions.get('rsi_9_oversold_threshold', 30)
    rsi_14_oversold_threshold = conditions.get('rsi_14_oversold_threshold', 30)
    
    if rsi_9 is not None and rsi_14 is not None:
        if rsi_9 < rsi_9_oversold_threshold and rsi_14 < rsi_14_oversold_threshold:
            return SignalType.DUAL_RSI.value
        elif rsi_9 < rsi_9_oversold_threshold:
            return SignalType.RSI_9_ONLY.value
        elif rsi_14 < rsi_14_oversold_threshold:
            return SignalType.RSI_14_ONLY.value
    
    return SignalType.UNKNOWN.value


def map_exit_reason_to_enum(exit_reason_str: str) -> str:
    """
    Map exit reason string to ExitReason enum value.
    
    Args:
        exit_reason_str: Exit reason string from trading logic
    
    Returns:
        ExitReason enum value as string
    """
    # Normalize the input
    reason_lower = exit_reason_str.lower()
    
    # Profit targets
    if 'profit' in reason_lower and 'target' in reason_lower:
        if '25%' in reason_lower or 'first' in reason_lower:
            return ExitReason.PROFIT_TARGET_1.value
        elif '50%' in reason_lower or 'second' in reason_lower:
            return ExitReason.PROFIT_TARGET_2.value
        elif '75%' in reason_lower or 'third' in reason_lower:
            return ExitReason.PROFIT_TARGET_3.value
        else:
            return ExitReason.FULL_PROFIT_TARGET.value
    
    # Trailing stop
    if 'trailing' in reason_lower:
        return ExitReason.TRAILING_STOP_HIT.value
    
    # Stop losses
    if 'stop' in reason_lower and 'loss' in reason_lower:
        return ExitReason.STOP_LOSS_HIT.value
    
    if 'time' in reason_lower or 'age' in reason_lower or 'hours' in reason_lower:
        return ExitReason.TIME_BASED_STOP.value
    
    if 'losing' in reason_lower and 'trade' in reason_lower:
        return ExitReason.LOSING_TRADE_EXIT.value
    
    # RSI exits
    if 'rsi' in reason_lower:
        if 'overbought' in reason_lower:
            return ExitReason.RSI_OVERBOUGHT.value
        elif 'oversold' in reason_lower:
            return ExitReason.RSI_OVERSOLD_EXIT.value
    
    # Risk management
    if 'daily' in reason_lower and 'loss' in reason_lower:
        return ExitReason.DAILY_LOSS_LIMIT.value
    
    if 'position' in reason_lower and ('cap' in reason_lower or 'limit' in reason_lower):
        return ExitReason.POSITION_LIMIT_ENFORCEMENT.value
    
    if 'kill' in reason_lower and 'switch' in reason_lower:
        return ExitReason.KILL_SWITCH.value
    
    if 'liquidate' in reason_lower:
        return ExitReason.LIQUIDATE_ALL.value
    
    # Position cleanup
    if 'dust' in reason_lower or 'small' in reason_lower:
        return ExitReason.DUST_POSITION.value
    
    if 'zombie' in reason_lower or 'stuck' in reason_lower:
        return ExitReason.ZOMBIE_POSITION.value
    
    if 'adoption' in reason_lower or 'adopted' in reason_lower:
        return ExitReason.ADOPTION_EXIT.value
    
    # Manual
    if 'manual' in reason_lower:
        return ExitReason.MANUAL_EXIT.value
    
    # Fallback
    return ExitReason.UNKNOWN.value


# Convenience function to get analytics instance
def get_analytics_instance():
    """Get the singleton analytics instance"""
    return get_analytics()
