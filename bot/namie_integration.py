"""
NAMIE Integration Helper
=========================

Integration layer to connect NAMIE with existing NIJA trading strategies.
Makes it easy to add NAMIE intelligence to any strategy.

Usage:
    from bot.namie_integration import NAMIEIntegration
    
    # In your strategy
    namie = NAMIEIntegration()
    signal = namie.analyze(df, indicators, symbol)
    
    if signal.should_trade:
        # Proceed with entry logic
        adjusted_size = base_size * signal.position_size_multiplier

Author: NIJA Trading Systems
Version: 1.0
Date: January 30, 2026
"""

import logging
from typing import Dict, Optional, Tuple
import pandas as pd

try:
    from bot.namie_core import NAMIECore, NAMIESignal, get_namie_engine
    from bot.namie_strategy_switcher import NAMIEStrategySwitcher, get_strategy_switcher
    from bot.regime_strategy_selector import TradingStrategy
except ImportError:
    from namie_core import NAMIECore, NAMIESignal, get_namie_engine
    from namie_strategy_switcher import NAMIEStrategySwitcher, get_strategy_switcher
    from regime_strategy_selector import TradingStrategy

logger = logging.getLogger("nija.namie_integration")


class NAMIEIntegration:
    """
    Easy-to-use integration layer for NAMIE
    
    Provides simple interface to add NAMIE intelligence to existing strategies.
    """
    
    def __init__(self, config: Dict = None, enable_switcher: bool = True):
        """
        Initialize NAMIE integration
        
        Args:
            config: Optional configuration dictionary
            enable_switcher: Enable automatic strategy switching
        """
        self.config = config or {}
        self.enable_switcher = enable_switcher
        
        # Get NAMIE components
        self.namie_core = get_namie_engine(self.config)
        
        if self.enable_switcher:
            self.strategy_switcher = get_strategy_switcher(self.config)
        else:
            self.strategy_switcher = None
        
        # Integration settings
        self.respect_namie_decisions = self.config.get('respect_namie_decisions', True)
        self.override_position_sizing = self.config.get('override_position_sizing', True)
        self.override_entry_thresholds = self.config.get('override_entry_thresholds', True)
        
        logger.info("🧠 NAMIE Integration initialized")
        logger.info(f"   Strategy Switching: {'✅ Enabled' if enable_switcher else '❌ Disabled'}")
        logger.info(f"   Respect NAMIE decisions: {self.respect_namie_decisions}")
    
    def analyze(
        self,
        df: pd.DataFrame,
        indicators: Dict,
        symbol: str = "UNKNOWN"
    ) -> NAMIESignal:
        """
        Analyze market and get NAMIE intelligence signal
        
        Args:
            df: Price DataFrame with OHLCV data
            indicators: Dictionary of calculated technical indicators
            symbol: Trading symbol
        
        Returns:
            NAMIESignal with comprehensive market intelligence
        """
        # Get NAMIE analysis
        signal = self.namie_core.analyze_market(df, indicators, symbol)
        
        # If strategy switching enabled, select optimal strategy
        if self.strategy_switcher:
            strategy, reason = self.strategy_switcher.select_strategy(signal)
            signal.optimal_strategy = strategy
            
            logger.debug(f"Strategy selected for {symbol}: {strategy.value} - {reason}")
        
        return signal
    
    def should_enter_trade(
        self,
        signal: NAMIESignal,
        base_entry_score: int,
        base_should_enter: bool
    ) -> Tuple[bool, str]:
        """
        Determine if trade should be entered based on NAMIE + base strategy
        
        Args:
            signal: NAMIE intelligence signal
            base_entry_score: Entry score from base strategy (e.g., 0-5)
            base_should_enter: Whether base strategy says to enter
        
        Returns:
            Tuple of (should_enter, reason)
        """
        # If NAMIE blocks trading, respect it (if configured)
        if self.respect_namie_decisions and not signal.should_trade:
            return False, f"NAMIE: {signal.trade_reason}"
        
        # Check if base entry score meets NAMIE's threshold
        if self.override_entry_thresholds:
            if base_entry_score < signal.min_entry_score_required:
                return False, f"NAMIE: Entry score {base_entry_score} < required {signal.min_entry_score_required}"
        
        # Both NAMIE and base strategy approve
        if base_should_enter and signal.should_trade:
            return True, f"NAMIE + Strategy approval (Regime: {signal.regime.value})"
        
        # Base strategy approves but NAMIE has concerns
        if base_should_enter and not signal.should_trade:
            if self.respect_namie_decisions:
                return False, f"NAMIE override: {signal.trade_reason}"
            else:
                return True, "Base strategy approved (NAMIE override disabled)"
        
        # Base strategy blocks
        return False, "Base strategy blocked entry"
    
    def adjust_position_size(
        self,
        signal: NAMIESignal,
        base_position_size: float
    ) -> float:
        """
        Adjust position size based on NAMIE intelligence
        
        Args:
            signal: NAMIE intelligence signal
            base_position_size: Base position size from strategy
        
        Returns:
            Adjusted position size
        """
        if not self.override_position_sizing:
            return base_position_size
        
        # Apply NAMIE multiplier
        adjusted_size = base_position_size * signal.position_size_multiplier
        
        logger.debug(
            f"Position size adjusted: ${base_position_size:.2f} → ${adjusted_size:.2f} "
            f"({signal.position_size_multiplier:.2f}x for {signal.regime.value})"
        )
        
        return adjusted_size
    
    def get_adaptive_rsi_ranges(self, signal: NAMIESignal, adx: float = None) -> Dict[str, float]:
        """
        Get adaptive RSI ranges based on NAMIE regime detection
        
        Args:
            signal: NAMIE intelligence signal
            adx: Optional ADX value for fine-tuning
        
        Returns:
            Dictionary with RSI ranges: {'long_min', 'long_max', 'short_min', 'short_max'}
        """
        return self.namie_core.regime_detector.get_adaptive_rsi_ranges(
            signal.regime,
            adx=adx or signal.metrics.get('adx')
        )
    
    def record_trade_result(
        self,
        signal: NAMIESignal,
        entry_price: float,
        exit_price: float,
        side: str,
        size_usd: float,
        commission: float = 0.0
    ):
        """
        Record trade result for NAMIE learning
        
        Args:
            signal: NAMIE signal that triggered the trade
            entry_price: Entry price
            exit_price: Exit price
            side: 'long' or 'short'
            size_usd: Position size in USD
            commission: Trading commission
        """
        # Calculate PnL
        if side.lower() == 'long':
            pnl_pct = (exit_price - entry_price) / entry_price
        else:
            pnl_pct = (entry_price - exit_price) / entry_price
        
        pnl_usd = size_usd * pnl_pct - commission
        is_win = pnl_usd > 0
        
        # Update NAMIE core performance
        self.namie_core.update_performance(signal.regime, is_win, pnl_usd)
        
        # Update strategy switcher performance (if enabled)
        if self.strategy_switcher:
            self.strategy_switcher.record_trade(
                strategy=signal.optimal_strategy,
                regime=signal.regime,
                entry_price=entry_price,
                exit_price=exit_price,
                side=side,
                size_usd=size_usd,
                commission=commission
            )
    
    def get_performance_summary(self) -> Dict:
        """
        Get comprehensive performance summary
        
        Returns:
            Dictionary with performance metrics from all NAMIE components
        """
        summary = {
            'namie_core': self.namie_core.get_performance_summary(),
        }
        
        if self.strategy_switcher:
            summary['strategy_switcher'] = self.strategy_switcher.get_performance_summary()
        
        return summary
    
    def get_current_strategy(self, signal: NAMIESignal) -> TradingStrategy:
        """
        Get currently active strategy for the detected regime
        
        Args:
            signal: NAMIE signal
        
        Returns:
            Active trading strategy
        """
        if self.strategy_switcher:
            return self.strategy_switcher.get_strategy_for_regime(signal.regime)
        else:
            return signal.optimal_strategy


# Convenience function for quick integration
def quick_namie_check(
    df: pd.DataFrame,
    indicators: Dict,
    symbol: str = "UNKNOWN",
    config: Dict = None
) -> Tuple[bool, str, NAMIESignal]:
    """
    Quick NAMIE check - single function call for simple integration
    
    Args:
        df: Price DataFrame
        indicators: Technical indicators
        symbol: Trading symbol
        config: Optional configuration
    
    Returns:
        Tuple of (should_trade, reason, full_signal)
    
    Example:
        should_trade, reason, signal = quick_namie_check(df, indicators, "BTC-USD")
        if should_trade:
            # Execute trade with adjusted size
            size = base_size * signal.position_size_multiplier
    """
    namie = NAMIEIntegration(config=config)
    signal = namie.analyze(df, indicators, symbol)
    
    return signal.should_trade, signal.trade_reason, signal
