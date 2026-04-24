"""
NAMIE Strategy Switcher
========================

Auto-switches trading strategies based on NAMIE market intelligence:
- Tracks strategy performance per market regime
- Implements intelligent fallback logic
- Optimizes strategy allocation
- Prevents chop losses through smart filtering

Author: NIJA Trading Systems
Version: 1.0
Date: January 30, 2026
"""

import logging
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict, deque
from enum import Enum

try:
    from bot.namie_core import NAMIESignal, MarketRegime, TrendStrength, ChopCondition
    from bot.regime_strategy_selector import TradingStrategy
except ImportError:
    from namie_core import NAMIESignal, MarketRegime, TrendStrength, ChopCondition
    from regime_strategy_selector import TradingStrategy

logger = logging.getLogger("nija.namie_switcher")


@dataclass
class StrategyPerformance:
    """Track performance metrics for a strategy in a specific regime"""
    strategy: TradingStrategy
    regime: MarketRegime
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    total_commission: float = 0.0
    max_drawdown: float = 0.0
    current_drawdown: float = 0.0
    peak_equity: float = 0.0
    recent_trades: deque = field(default_factory=lambda: deque(maxlen=20))
    
    @property
    def win_rate(self) -> float:
        """Calculate win rate"""
        if self.total_trades == 0:
            return 0.0
        return self.winning_trades / self.total_trades
    
    @property
    def profit_factor(self) -> float:
        """Calculate profit factor (gross profit / gross loss)"""
        gross_profit = sum(t['pnl'] for t in self.recent_trades if t['pnl'] > 0)
        gross_loss = abs(sum(t['pnl'] for t in self.recent_trades if t['pnl'] < 0))
        
        if gross_loss == 0:
            return float('inf') if gross_profit > 0 else 0.0
        return gross_profit / gross_loss
    
    @property
    def avg_trade(self) -> float:
        """Calculate average trade PnL"""
        if self.total_trades == 0:
            return 0.0
        return self.total_pnl / self.total_trades
    
    @property
    def sharpe_estimate(self) -> float:
        """Estimate Sharpe ratio from recent trades"""
        if len(self.recent_trades) < 5:
            return 0.0
        
        pnls = [t['pnl'] for t in self.recent_trades]
        avg_pnl = np.mean(pnls)
        std_pnl = np.std(pnls)
        
        if std_pnl == 0:
            return 0.0
        
        # Annualized Sharpe (assuming daily trades)
        return (avg_pnl / std_pnl) * np.sqrt(252)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'strategy': self.strategy.value,
            'regime': self.regime.value,
            'total_trades': self.total_trades,
            'win_rate': self.win_rate,
            'profit_factor': self.profit_factor,
            'total_pnl': self.total_pnl,
            'avg_trade': self.avg_trade,
            'max_drawdown': self.max_drawdown,
            'sharpe_estimate': self.sharpe_estimate,
        }


@dataclass
class StrategySwitch:
    """Record of a strategy switch event"""
    timestamp: datetime
    from_strategy: TradingStrategy
    to_strategy: TradingStrategy
    regime: MarketRegime
    reason: str
    namie_signal: Optional[NAMIESignal] = None


class NAMIEStrategySwitcher:
    """
    Intelligent strategy switching system powered by NAMIE
    
    Features:
    - Performance-based strategy selection
    - Regime-aware switching
    - Drawdown protection
    - Chop prevention
    - Strategy allocation optimization
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize NAMIE Strategy Switcher
        
        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}
        
        # Strategy switching parameters
        self.min_trades_for_switch = self.config.get('min_trades_for_switch', 10)
        self.performance_lookback = self.config.get('performance_lookback', 20)
        self.switch_threshold_win_rate = self.config.get('switch_threshold_win_rate', 0.45)
        self.switch_threshold_profit_factor = self.config.get('switch_threshold_profit_factor', 0.8)
        
        # Drawdown protection
        self.max_strategy_drawdown = self.config.get('max_strategy_drawdown', 0.15)  # 15%
        
        # Performance tracking
        self.performance_by_strategy_regime: Dict[Tuple[TradingStrategy, MarketRegime], StrategyPerformance] = {}
        self.current_strategy_by_regime: Dict[MarketRegime, TradingStrategy] = {
            MarketRegime.TRENDING: TradingStrategy.TREND,
            MarketRegime.RANGING: TradingStrategy.MEAN_REVERSION,
            MarketRegime.VOLATILE: TradingStrategy.BREAKOUT,
        }
        
        # Switch history
        self.switch_history: List[StrategySwitch] = []
        self.last_switch_time: Dict[MarketRegime, datetime] = {}
        
        # Min time between switches (prevent over-switching)
        self.min_switch_interval = timedelta(hours=self.config.get('min_switch_interval_hours', 4))
        
        logger.info("🔄 NAMIE Strategy Switcher initialized")
        logger.info(f"   Min trades for switch: {self.min_trades_for_switch}")
        logger.info(f"   Switch threshold win rate: {self.switch_threshold_win_rate:.0%}")
        logger.info(f"   Max strategy drawdown: {self.max_strategy_drawdown:.0%}")
    
    def select_strategy(self, namie_signal: NAMIESignal) -> Tuple[TradingStrategy, str]:
        """
        Select best strategy based on NAMIE signal and performance tracking
        
        Args:
            namie_signal: NAMIE market intelligence signal
        
        Returns:
            Tuple of (selected_strategy, reason)
        """
        regime = namie_signal.regime
        
        # Get current strategy for this regime
        current_strategy = self.current_strategy_by_regime.get(regime, TradingStrategy.NONE)
        
        # Check if we should switch strategies
        should_switch, new_strategy, reason = self._evaluate_switch(namie_signal, current_strategy)
        
        if should_switch:
            # Record the switch
            switch = StrategySwitch(
                timestamp=datetime.utcnow(),
                from_strategy=current_strategy,
                to_strategy=new_strategy,
                regime=regime,
                reason=reason,
                namie_signal=namie_signal
            )
            self.switch_history.append(switch)
            self.last_switch_time[regime] = datetime.utcnow()
            self.current_strategy_by_regime[regime] = new_strategy
            
            logger.info(
                f"🔄 Strategy Switch [{regime.value}]: {current_strategy.value} → {new_strategy.value} | {reason}"
            )
            
            return new_strategy, reason
        else:
            return current_strategy, f"Keeping {current_strategy.value}"
    
    def _evaluate_switch(
        self,
        namie_signal: NAMIESignal,
        current_strategy: TradingStrategy
    ) -> Tuple[bool, TradingStrategy, str]:
        """
        Evaluate if strategy should be switched
        
        Returns:
            Tuple of (should_switch, new_strategy, reason)
        """
        regime = namie_signal.regime
        
        # Rule 1: If NAMIE recommends a different strategy with high confidence
        if namie_signal.optimal_strategy != current_strategy and \
           namie_signal.strategy_confidence > 0.8:
            return True, namie_signal.optimal_strategy, f"NAMIE high confidence ({namie_signal.strategy_confidence:.0%})"
        
        # Rule 2: Check if current strategy is underperforming
        perf_key = (current_strategy, regime)
        if perf_key in self.performance_by_strategy_regime:
            perf = self.performance_by_strategy_regime[perf_key]
            
            # Need minimum trades to evaluate
            if perf.total_trades >= self.min_trades_for_switch:
                # Check win rate
                if perf.win_rate < self.switch_threshold_win_rate:
                    best_alt = self._find_best_alternative(regime, current_strategy)
                    if best_alt:
                        return True, best_alt, f"Low win rate ({perf.win_rate:.0%})"
                
                # Check profit factor
                if perf.profit_factor < self.switch_threshold_profit_factor:
                    best_alt = self._find_best_alternative(regime, current_strategy)
                    if best_alt:
                        return True, best_alt, f"Low profit factor ({perf.profit_factor:.2f})"
                
                # Check drawdown
                if perf.current_drawdown > self.max_strategy_drawdown:
                    best_alt = self._find_best_alternative(regime, current_strategy)
                    if best_alt:
                        return True, best_alt, f"Excessive drawdown ({perf.current_drawdown:.1%})"
        
        # Rule 3: Prevent trading in severe chop conditions
        if namie_signal.chop_condition in [ChopCondition.SEVERE, ChopCondition.EXTREME]:
            # Switch to NONE (no trading) in extreme chop
            if current_strategy != TradingStrategy.NONE:
                return True, TradingStrategy.NONE, f"Severe chop ({namie_signal.chop_score:.0f})"
        
        # Rule 4: Check switch cooldown
        if regime in self.last_switch_time:
            time_since_switch = datetime.utcnow() - self.last_switch_time[regime]
            if time_since_switch < self.min_switch_interval:
                # Too soon to switch again
                return False, current_strategy, "Switch cooldown active"
        
        # No switch needed
        return False, current_strategy, "Current strategy performing well"
    
    def _find_best_alternative(
        self,
        regime: MarketRegime,
        exclude_strategy: TradingStrategy
    ) -> Optional[TradingStrategy]:
        """
        Find best performing alternative strategy for given regime
        
        Args:
            regime: Market regime
            exclude_strategy: Strategy to exclude from consideration
        
        Returns:
            Best alternative strategy or None
        """
        # Get all strategies tested in this regime
        alternatives = []
        for (strategy, test_regime), perf in self.performance_by_strategy_regime.items():
            if test_regime == regime and strategy != exclude_strategy:
                # Only consider strategies with enough data
                if perf.total_trades >= self.min_trades_for_switch:
                    score = self._score_strategy_performance(perf)
                    alternatives.append((strategy, score, perf))
        
        if not alternatives:
            # No alternatives with enough data, use NAMIE recommendation
            return None
        
        # Sort by score (higher is better)
        alternatives.sort(key=lambda x: x[1], reverse=True)
        
        # Return best alternative
        best_strategy, best_score, best_perf = alternatives[0]
        
        logger.debug(
            f"Best alternative for {regime.value}: {best_strategy.value} "
            f"(score={best_score:.2f}, WR={best_perf.win_rate:.0%}, PF={best_perf.profit_factor:.2f})"
        )
        
        return best_strategy
    
    def _score_strategy_performance(self, perf: StrategyPerformance) -> float:
        """
        Calculate composite performance score for a strategy
        
        Higher is better. Combines:
        - Win rate (40%)
        - Profit factor (30%)
        - Sharpe ratio (20%)
        - Drawdown penalty (10%)
        
        Returns:
            Performance score (0-100)
        """
        # Win rate component (0-40 points)
        win_rate_score = perf.win_rate * 40
        
        # Profit factor component (0-30 points)
        # Target PF of 2.0+ = 30 points
        pf_score = min(30, (perf.profit_factor / 2.0) * 30)
        
        # Sharpe component (0-20 points)
        # Target Sharpe of 2.0+ = 20 points
        sharpe_score = min(20, (perf.sharpe_estimate / 2.0) * 20)
        
        # Drawdown penalty (0-10 points deduction)
        # Max drawdown of 0% = 10 points, 15% = 0 points
        dd_penalty = max(0, 10 - (perf.max_drawdown / 0.15) * 10)
        
        total_score = win_rate_score + pf_score + sharpe_score + dd_penalty
        
        return total_score
    
    def record_trade(
        self,
        strategy: TradingStrategy,
        regime: MarketRegime,
        entry_price: float,
        exit_price: float,
        side: str,
        size_usd: float,
        commission: float = 0.0
    ):
        """
        Record trade result for performance tracking
        
        Args:
            strategy: Strategy that generated the trade
            regime: Market regime during trade
            entry_price: Entry price
            exit_price: Exit price
            side: 'long' or 'short'
            size_usd: Position size in USD
            commission: Trading commission paid
        """
        # Calculate PnL
        if side.lower() == 'long':
            pnl_pct = (exit_price - entry_price) / entry_price
        else:  # short
            pnl_pct = (entry_price - exit_price) / entry_price
        
        pnl_usd = size_usd * pnl_pct - commission
        is_win = pnl_usd > 0
        
        # Get or create performance tracker (key = strategy + regime combination)
        strategy_regime_key = (strategy, regime)
        if strategy_regime_key not in self.performance_by_strategy_regime:
            self.performance_by_strategy_regime[strategy_regime_key] = StrategyPerformance(
                strategy=strategy,
                regime=regime
            )
        
        perf = self.performance_by_strategy_regime[strategy_regime_key]
        
        # Update metrics
        perf.total_trades += 1
        if is_win:
            perf.winning_trades += 1
        else:
            perf.losing_trades += 1
        
        perf.total_pnl += pnl_usd
        perf.total_commission += commission
        
        # Track drawdown
        # Initialize peak equity to first trade if not set
        if perf.peak_equity == 0.0 and pnl_usd != 0:
            perf.peak_equity = max(0.0, pnl_usd)
        
        # Update peak equity if we hit a new high
        if perf.total_pnl > perf.peak_equity:
            perf.peak_equity = perf.total_pnl
        
        # Calculate current drawdown
        # Only calculate if we have a positive peak (otherwise drawdown is meaningless)
        if perf.peak_equity > 0:
            perf.current_drawdown = (perf.peak_equity - perf.total_pnl) / perf.peak_equity
        else:
            # If peak is 0 or negative, set drawdown to 0 (no meaningful drawdown)
            perf.current_drawdown = 0.0
        
        if perf.current_drawdown > perf.max_drawdown:
            perf.max_drawdown = perf.current_drawdown
        
        # Add to recent trades
        trade_record = {
            'timestamp': datetime.utcnow(),
            'entry_price': entry_price,
            'exit_price': exit_price,
            'side': side,
            'size_usd': size_usd,
            'pnl': pnl_usd,
            'commission': commission,
            'is_win': is_win,
        }
        perf.recent_trades.append(trade_record)
        
        logger.debug(
            f"📊 Trade Recorded [{strategy.value}/{regime.value}]: "
            f"{'WIN' if is_win else 'LOSS'} ${pnl_usd:.2f} | "
            f"Stats: {perf.total_trades} trades, WR={perf.win_rate:.0%}, PF={perf.profit_factor:.2f}"
        )
    
    def get_strategy_for_regime(self, regime: MarketRegime) -> TradingStrategy:
        """
        Get currently active strategy for a regime
        
        Args:
            regime: Market regime
        
        Returns:
            Active trading strategy
        """
        return self.current_strategy_by_regime.get(regime, TradingStrategy.NONE)
    
    def get_performance_summary(self) -> Dict:
        """
        Get comprehensive performance summary
        
        Returns:
            Dictionary with performance metrics
        """
        summary = {
            'by_strategy_regime': {},
            'by_regime': defaultdict(lambda: {'trades': 0, 'wins': 0, 'total_pnl': 0.0}),
            'by_strategy': defaultdict(lambda: {'trades': 0, 'wins': 0, 'total_pnl': 0.0}),
            'current_allocations': {},
            'recent_switches': []
        }
        
        # Aggregate by strategy-regime
        for (strategy, regime), perf in self.performance_by_strategy_regime.items():
            key = f"{strategy.value}_{regime.value}"
            summary['by_strategy_regime'][key] = perf.to_dict()
            
            # Aggregate by regime
            summary['by_regime'][regime.value]['trades'] += perf.total_trades
            summary['by_regime'][regime.value]['wins'] += perf.winning_trades
            summary['by_regime'][regime.value]['total_pnl'] += perf.total_pnl
            
            # Aggregate by strategy
            summary['by_strategy'][strategy.value]['trades'] += perf.total_trades
            summary['by_strategy'][strategy.value]['wins'] += perf.winning_trades
            summary['by_strategy'][strategy.value]['total_pnl'] += perf.total_pnl
        
        # Current strategy allocations
        for regime, strategy in self.current_strategy_by_regime.items():
            summary['current_allocations'][regime.value] = strategy.value
        
        # Recent switches
        for switch in self.switch_history[-10:]:  # Last 10 switches
            summary['recent_switches'].append({
                'timestamp': switch.timestamp.isoformat(),
                'from': switch.from_strategy.value,
                'to': switch.to_strategy.value,
                'regime': switch.regime.value,
                'reason': switch.reason,
            })
        
        return summary
    
    def reset_performance(self, strategy: Optional[TradingStrategy] = None, regime: Optional[MarketRegime] = None):
        """
        Reset performance tracking (use with caution)
        
        Args:
            strategy: Optional strategy to reset (None = all)
            regime: Optional regime to reset (None = all)
        """
        if strategy is None and regime is None:
            # Reset everything
            self.performance_by_strategy_regime.clear()
            logger.warning("🔄 All performance data reset")
        else:
            # Reset specific combinations
            keys_to_reset = []
            for key in self.performance_by_strategy_regime.keys():
                strat, reg = key
                if (strategy is None or strat == strategy) and \
                   (regime is None or reg == regime):
                    keys_to_reset.append(key)
            
            for key in keys_to_reset:
                del self.performance_by_strategy_regime[key]
            
            logger.warning(f"🔄 Performance data reset for {len(keys_to_reset)} combinations")


# Global instance
_switcher_instance = None


def get_strategy_switcher(config: Dict = None) -> NAMIEStrategySwitcher:
    """
    Get or create global strategy switcher instance
    
    Args:
        config: Optional configuration dictionary
    
    Returns:
        NAMIEStrategySwitcher instance
    """
    global _switcher_instance
    if _switcher_instance is None:
        _switcher_instance = NAMIEStrategySwitcher(config)
    return _switcher_instance
