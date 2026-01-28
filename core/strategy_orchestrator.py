"""
NIJA Multi-Strategy Orchestrator
=================================

Intelligent orchestration layer that manages multiple trading strategies simultaneously.
Automatically selects and allocates capital to the best-performing strategies based on:
- Market regime detection
- Real-time performance metrics
- Risk-adjusted returns
- Strategy correlation
- Execution quality

This is the "Brain" of NIJA - the central intelligence that coordinates all trading decisions.

Features:
1. Dynamic strategy selection based on market conditions
2. Real-time performance tracking and comparison
3. Adaptive capital allocation using Kelly Criterion variant
4. Strategy ensemble voting for high-confidence signals
5. Automatic strategy rotation based on performance
6. Risk correlation management across strategies

Author: NIJA Trading Systems
Version: 1.0
Date: January 2026
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
from dataclasses import dataclass, field
from collections import defaultdict, deque
import pandas as pd
import numpy as np

logger = logging.getLogger("nija.orchestrator")


class StrategyState(Enum):
    """Strategy lifecycle states"""
    ACTIVE = "active"           # Actively trading
    MONITORING = "monitoring"   # Watching performance but not trading
    DISABLED = "disabled"       # Temporarily disabled due to poor performance
    RETIRED = "retired"         # Permanently removed from rotation


@dataclass
class StrategyPerformance:
    """Track strategy performance metrics"""
    strategy_id: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    total_fees: float = 0.0
    max_drawdown: float = 0.0
    current_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    
    # Recent performance tracking
    last_30_trades: deque = field(default_factory=lambda: deque(maxlen=30))
    last_30_pnl: float = 0.0
    last_30_win_rate: float = 0.0
    
    # Regime-specific performance
    regime_performance: Dict[str, Dict] = field(default_factory=dict)
    
    # Timestamp tracking
    last_trade_time: Optional[datetime] = None
    last_update_time: datetime = field(default_factory=datetime.now)
    
    def update_trade(self, pnl: float, fees: float, regime: str = "unknown"):
        """Update metrics with new trade result"""
        self.total_trades += 1
        self.total_pnl += pnl
        self.total_fees += fees
        net_pnl = pnl - fees
        
        # Update win/loss counts
        if net_pnl > 0:
            self.winning_trades += 1
            self.avg_win = ((self.avg_win * (self.winning_trades - 1)) + net_pnl) / self.winning_trades
        else:
            self.losing_trades += 1
            self.avg_loss = ((self.avg_loss * (self.losing_trades - 1)) + abs(net_pnl)) / self.losing_trades
        
        # Update win rate
        self.win_rate = self.winning_trades / self.total_trades if self.total_trades > 0 else 0
        
        # Update profit factor
        total_wins = self.avg_win * self.winning_trades
        total_losses = self.avg_loss * self.losing_trades
        self.profit_factor = total_wins / total_losses if total_losses > 0 else 0
        
        # Update last 30 trades
        self.last_30_trades.append(net_pnl)
        self.last_30_pnl = sum(self.last_30_trades)
        wins_30 = sum(1 for x in self.last_30_trades if x > 0)
        self.last_30_win_rate = wins_30 / len(self.last_30_trades) if self.last_30_trades else 0
        
        # Update drawdown
        if self.total_pnl > 0:
            self.current_drawdown = 0
        else:
            self.current_drawdown = abs(self.total_pnl)
        self.max_drawdown = max(self.max_drawdown, self.current_drawdown)
        
        # Update regime-specific performance
        if regime not in self.regime_performance:
            self.regime_performance[regime] = {
                'trades': 0, 'wins': 0, 'pnl': 0.0, 'win_rate': 0.0
            }
        
        regime_stats = self.regime_performance[regime]
        regime_stats['trades'] += 1
        regime_stats['pnl'] += net_pnl
        if net_pnl > 0:
            regime_stats['wins'] += 1
        regime_stats['win_rate'] = regime_stats['wins'] / regime_stats['trades']
        
        # Update timestamps
        self.last_trade_time = datetime.now()
        self.last_update_time = datetime.now()
    
    def calculate_sharpe_ratio(self, returns: List[float], risk_free_rate: float = 0.0) -> float:
        """Calculate Sharpe ratio from returns"""
        if len(returns) < 2:
            return 0.0
        
        returns_array = np.array(returns)
        excess_returns = returns_array - risk_free_rate
        
        if np.std(excess_returns) == 0:
            return 0.0
        
        sharpe = np.mean(excess_returns) / np.std(excess_returns)
        # Annualize (assuming daily returns)
        sharpe_annual = sharpe * np.sqrt(252)
        
        return sharpe_annual


@dataclass
class StrategyConfig:
    """Configuration for a strategy in the orchestrator"""
    strategy_id: str
    strategy_class: Any  # The actual strategy class
    strategy_instance: Any = None  # Initialized instance
    weight: float = 1.0  # Relative weight in ensemble
    min_capital_allocation: float = 100.0  # Minimum capital to allocate
    max_capital_allocation: float = 10000.0  # Maximum capital to allocate
    state: StrategyState = StrategyState.MONITORING
    preferred_regimes: List[str] = field(default_factory=list)  # Regimes where this strategy excels
    
    # Performance thresholds
    min_sharpe_ratio: float = 0.5  # Minimum Sharpe to stay active
    min_win_rate: float = 0.45  # Minimum win rate to stay active
    max_drawdown_pct: float = 0.15  # Maximum drawdown before disabling (15%)
    
    # Trade filtering
    min_confidence_score: float = 0.65  # Minimum signal confidence
    require_ensemble_confirmation: bool = False  # Require other strategies to agree


class StrategyOrchestrator:
    """
    Multi-Strategy Orchestration Engine
    
    Manages multiple trading strategies, dynamically allocates capital,
    and optimizes performance through intelligent strategy selection.
    """
    
    def __init__(self, total_capital: float, config: Optional[Dict] = None):
        """
        Initialize strategy orchestrator
        
        Args:
            total_capital: Total capital available for allocation
            config: Optional configuration dictionary
        """
        self.total_capital = total_capital
        self.config = config or {}
        
        # Strategy registry
        self.strategies: Dict[str, StrategyConfig] = {}
        self.performance: Dict[str, StrategyPerformance] = {}
        
        # Capital allocation
        self.capital_allocations: Dict[str, float] = {}
        self.reserve_capital_pct = self.config.get('reserve_capital_pct', 0.20)  # 20% reserve
        
        # Ensemble voting
        self.ensemble_voting_enabled = self.config.get('ensemble_voting_enabled', True)
        self.ensemble_min_votes = self.config.get('ensemble_min_votes', 2)  # Require 2+ strategies to agree
        
        # Performance review settings
        self.performance_review_interval = self.config.get('performance_review_interval', 3600)  # 1 hour
        self.last_review_time = datetime.now()
        
        # Regime detection
        try:
            from market_regime_detector import RegimeDetector
            self.regime_detector = RegimeDetector()
            self.regime_detection_enabled = True
        except ImportError:
            self.regime_detector = None
            self.regime_detection_enabled = False
            logger.warning("Regime detection not available - using static allocation")
        
        logger.info(f"Strategy Orchestrator initialized with ${total_capital:,.2f} total capital")
        logger.info(f"Reserve capital: {self.reserve_capital_pct*100:.0f}% (${total_capital*self.reserve_capital_pct:,.2f})")
    
    def register_strategy(self, strategy_config: StrategyConfig) -> bool:
        """
        Register a new strategy with the orchestrator
        
        Args:
            strategy_config: Strategy configuration
            
        Returns:
            bool: Success status
        """
        strategy_id = strategy_config.strategy_id
        
        if strategy_id in self.strategies:
            logger.warning(f"Strategy {strategy_id} already registered - updating config")
        
        # Initialize strategy instance if not provided
        if strategy_config.strategy_instance is None:
            try:
                strategy_config.strategy_instance = strategy_config.strategy_class()
            except Exception as e:
                logger.error(f"Failed to initialize strategy {strategy_id}: {e}")
                return False
        
        # Register strategy
        self.strategies[strategy_id] = strategy_config
        self.performance[strategy_id] = StrategyPerformance(strategy_id=strategy_id)
        
        # Initialize capital allocation
        if strategy_config.state == StrategyState.ACTIVE:
            self._allocate_capital_to_strategy(strategy_id)
        else:
            self.capital_allocations[strategy_id] = 0.0
        
        logger.info(f"✅ Registered strategy: {strategy_id} (state: {strategy_config.state.value})")
        return True
    
    def _allocate_capital_to_strategy(self, strategy_id: str) -> float:
        """
        Allocate capital to a strategy based on performance and risk
        
        Args:
            strategy_id: Strategy identifier
            
        Returns:
            float: Allocated capital amount
        """
        if strategy_id not in self.strategies:
            return 0.0
        
        config = self.strategies[strategy_id]
        perf = self.performance[strategy_id]
        
        # Available capital (total - reserve)
        available_capital = self.total_capital * (1 - self.reserve_capital_pct)
        
        # Calculate base allocation based on strategy weight
        total_weight = sum(s.weight for s in self.strategies.values() if s.state == StrategyState.ACTIVE)
        if total_weight == 0:
            return 0.0
        
        base_allocation = available_capital * (config.weight / total_weight)
        
        # Adjust based on performance (Kelly Criterion variant)
        if perf.total_trades >= 10:  # Need minimum trades for statistical significance
            # Kelly fraction: f = (win_rate * avg_win - loss_rate * avg_loss) / avg_win
            win_rate = perf.win_rate
            loss_rate = 1 - win_rate
            
            if perf.avg_win > 0:
                kelly_fraction = (win_rate * perf.avg_win - loss_rate * perf.avg_loss) / perf.avg_win
                kelly_fraction = max(0, min(kelly_fraction, 0.25))  # Cap at 25% (fractional Kelly)
                
                # Adjust allocation
                base_allocation *= (1 + kelly_fraction)
        
        # Apply min/max constraints
        allocation = max(config.min_capital_allocation, min(base_allocation, config.max_capital_allocation))
        
        # Apply drawdown penalty
        if perf.current_drawdown > 0:
            # Use 100 as minimum denominator to avoid division by zero and extreme ratios
            # This represents a minimum P&L baseline for drawdown calculations
            DRAWDOWN_BASELINE = 100.0
            drawdown_pct = perf.current_drawdown / max(abs(perf.total_pnl), DRAWDOWN_BASELINE)
            if drawdown_pct > 0.10:  # More than 10% drawdown
                allocation *= (1 - drawdown_pct)
        
        self.capital_allocations[strategy_id] = allocation
        
        logger.debug(f"Capital allocation for {strategy_id}: ${allocation:,.2f}")
        return allocation
    
    def get_trading_signals(self, symbol: str, df: pd.DataFrame, 
                          indicators: Dict, broker_name: str = "coinbase") -> List[Dict]:
        """
        Get trading signals from all active strategies
        
        Args:
            symbol: Trading symbol
            df: OHLCV DataFrame
            indicators: Calculated indicators
            broker_name: Broker name for exchange-specific logic
            
        Returns:
            List of signal dictionaries from each strategy
        """
        signals = []
        
        # Detect current market regime
        current_regime = "unknown"
        if self.regime_detection_enabled and self.regime_detector:
            try:
                regime, regime_metrics = self.regime_detector.detect_regime(df, indicators)
                current_regime = regime.value
            except Exception as e:
                logger.error(f"Error detecting regime: {e}")
        
        # Collect signals from all active strategies
        for strategy_id, config in self.strategies.items():
            if config.state != StrategyState.ACTIVE:
                continue
            
            # Check if strategy prefers this regime
            if config.preferred_regimes and current_regime not in config.preferred_regimes:
                logger.debug(f"Skipping {strategy_id} - not optimal for {current_regime} regime")
                continue
            
            try:
                # Get signal from strategy
                strategy = config.strategy_instance
                
                # Different strategies have different signal generation methods
                signal = self._get_strategy_signal(strategy, symbol, df, indicators, broker_name)
                
                if signal:
                    signal['strategy_id'] = strategy_id
                    signal['regime'] = current_regime
                    signal['capital_allocation'] = self.capital_allocations.get(strategy_id, 0)
                    signals.append(signal)
                    
            except Exception as e:
                logger.error(f"Error getting signal from {strategy_id}: {e}")
        
        return signals
    
    def _get_strategy_signal(self, strategy: Any, symbol: str, df: pd.DataFrame,
                           indicators: Dict, broker_name: str) -> Optional[Dict]:
        """
        Get signal from a specific strategy (handles different strategy interfaces)
        
        Args:
            strategy: Strategy instance
            symbol: Trading symbol
            df: OHLCV DataFrame
            indicators: Calculated indicators
            broker_name: Broker name
            
        Returns:
            Signal dictionary or None
        """
        signal = None
        
        # Try v7.2 strategy interface
        if hasattr(strategy, 'check_long_entry_v72'):
            should_enter, score, reason = strategy.check_long_entry_v72(df, indicators)
            if should_enter:
                # Calculate position size using v7.2 logic
                position_size = strategy.calculate_position_size_v72(
                    self.capital_allocations.get(strategy.__class__.__name__, 1000),
                    indicators.get('atr', 0)
                )
                
                signal = {
                    'action': 'long',
                    'confidence': score / 5.0,  # Normalize 0-5 to 0-1
                    'score': score,
                    'reason': reason,
                    'position_size': position_size,
                    'symbol': symbol
                }
        
        # Try v7.1 strategy interface
        elif hasattr(strategy, 'check_market_filter'):
            market_filter = strategy.check_market_filter(df, indicators)
            if market_filter:
                entry_signal, entry_score, entry_reason = strategy.check_long_entry(df, indicators)
                if entry_signal:
                    signal = {
                        'action': 'long',
                        'confidence': entry_score / 100.0,  # v7.1 uses 0-100 score
                        'score': entry_score,
                        'reason': entry_reason,
                        'symbol': symbol
                    }
        
        # Generic strategy interface
        elif hasattr(strategy, 'generate_signal'):
            signal = strategy.generate_signal(symbol, df, indicators, broker_name)
        
        return signal
    
    def execute_ensemble_vote(self, signals: List[Dict]) -> Optional[Dict]:
        """
        Use ensemble voting to determine final trading decision
        
        Args:
            signals: List of signals from different strategies
            
        Returns:
            Consolidated signal or None if no consensus
        """
        if not signals:
            return None
        
        if not self.ensemble_voting_enabled:
            # If voting disabled, return highest confidence signal
            return max(signals, key=lambda x: x.get('confidence', 0))
        
        # Count votes for each action
        action_votes = defaultdict(list)
        for signal in signals:
            action = signal.get('action', 'neutral')
            confidence = signal.get('confidence', 0)
            action_votes[action].append({
                'signal': signal,
                'confidence': confidence
            })
        
        # Find action with most votes
        max_votes = 0
        best_action = None
        for action, votes in action_votes.items():
            if len(votes) > max_votes:
                max_votes = len(votes)
                best_action = action
        
        # Check if we have minimum required votes
        if max_votes < self.ensemble_min_votes:
            logger.debug(f"Insufficient votes: {max_votes} < {self.ensemble_min_votes}")
            return None
        
        # Calculate weighted confidence from agreeing strategies
        agreeing_signals = action_votes[best_action]
        total_confidence = sum(v['confidence'] for v in agreeing_signals)
        avg_confidence = total_confidence / len(agreeing_signals)
        
        # Combine signals
        consensus_signal = {
            'action': best_action,
            'confidence': avg_confidence,
            'vote_count': max_votes,
            'agreeing_strategies': [v['signal']['strategy_id'] for v in agreeing_signals],
            'symbol': signals[0]['symbol']
        }
        
        # Average position sizes from agreeing strategies
        position_sizes = [v['signal'].get('position_size', 0) for v in agreeing_signals]
        if position_sizes:
            consensus_signal['position_size'] = np.mean(position_sizes)
        
        logger.info(f"✅ Ensemble consensus: {best_action} ({max_votes} votes, {avg_confidence:.2%} confidence)")
        
        return consensus_signal
    
    def record_trade_result(self, strategy_id: str, pnl: float, fees: float, regime: str = "unknown"):
        """
        Record trade result for performance tracking
        
        Args:
            strategy_id: Strategy that executed the trade
            pnl: Profit/loss amount
            fees: Trading fees
            regime: Market regime during trade
        """
        if strategy_id not in self.performance:
            logger.warning(f"Unknown strategy: {strategy_id}")
            return
        
        perf = self.performance[strategy_id]
        perf.update_trade(pnl, fees, regime)
        
        logger.info(f"📊 {strategy_id} trade result: ${pnl-fees:.2f} (regime: {regime})")
        logger.info(f"   Win rate: {perf.win_rate:.1%}, Total P&L: ${perf.total_pnl:.2f}")
    
    def review_strategy_performance(self) -> Dict[str, Any]:
        """
        Review performance of all strategies and adjust allocations
        
        Returns:
            Dictionary of review results and actions taken
        """
        review_results = {
            'timestamp': datetime.now(),
            'actions_taken': [],
            'strategy_status': {}
        }
        
        for strategy_id, config in self.strategies.items():
            perf = self.performance[strategy_id]
            
            # Skip if insufficient trades for review
            if perf.total_trades < 10:
                continue
            
            status = {
                'total_trades': perf.total_trades,
                'win_rate': perf.win_rate,
                'total_pnl': perf.total_pnl,
                'sharpe_ratio': perf.sharpe_ratio,
                'drawdown': perf.current_drawdown,
                'state': config.state.value
            }
            
            # Check performance thresholds
            actions = []
            
            # Win rate check
            if perf.win_rate < config.min_win_rate:
                if config.state == StrategyState.ACTIVE:
                    config.state = StrategyState.MONITORING
                    actions.append(f"Disabled due to low win rate: {perf.win_rate:.1%}")
            
            # Sharpe ratio check
            if perf.sharpe_ratio < config.min_sharpe_ratio and perf.total_trades >= 30:
                if config.state == StrategyState.ACTIVE:
                    config.state = StrategyState.MONITORING
                    actions.append(f"Disabled due to low Sharpe: {perf.sharpe_ratio:.2f}")
            
            # Drawdown check
            if perf.current_drawdown > 0:
                drawdown_pct = perf.current_drawdown / max(abs(perf.total_pnl), 100)
                if drawdown_pct > config.max_drawdown_pct:
                    if config.state == StrategyState.ACTIVE:
                        config.state = StrategyState.DISABLED
                        actions.append(f"Disabled due to drawdown: {drawdown_pct:.1%}")
            
            # Promotion to active if performing well
            if config.state == StrategyState.MONITORING:
                if (perf.win_rate > config.min_win_rate * 1.1 and  # 10% above minimum
                    perf.last_30_win_rate > 0.50 and  # Recent performance good
                    perf.current_drawdown == 0):  # Not in drawdown
                    config.state = StrategyState.ACTIVE
                    actions.append("Promoted to ACTIVE - strong performance")
            
            status['actions'] = actions
            review_results['strategy_status'][strategy_id] = status
            review_results['actions_taken'].extend(actions)
        
        # Rebalance capital allocations
        for strategy_id in self.strategies:
            if self.strategies[strategy_id].state == StrategyState.ACTIVE:
                self._allocate_capital_to_strategy(strategy_id)
        
        self.last_review_time = datetime.now()
        
        logger.info(f"📋 Strategy performance review complete - {len(review_results['actions_taken'])} actions taken")
        
        return review_results
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """
        Get comprehensive performance summary for all strategies
        
        Returns:
            Performance summary dictionary
        """
        summary = {
            'timestamp': datetime.now(),
            'total_capital': self.total_capital,
            'allocated_capital': sum(self.capital_allocations.values()),
            'reserve_capital': self.total_capital * self.reserve_capital_pct,
            'strategies': {}
        }
        
        # Aggregate metrics
        total_trades = 0
        total_pnl = 0.0
        total_fees = 0.0
        
        for strategy_id, perf in self.performance.items():
            config = self.strategies[strategy_id]
            
            summary['strategies'][strategy_id] = {
                'state': config.state.value,
                'total_trades': perf.total_trades,
                'win_rate': perf.win_rate,
                'total_pnl': perf.total_pnl,
                'net_pnl': perf.total_pnl - perf.total_fees,
                'sharpe_ratio': perf.sharpe_ratio,
                'profit_factor': perf.profit_factor,
                'max_drawdown': perf.max_drawdown,
                'capital_allocation': self.capital_allocations.get(strategy_id, 0),
                'last_30_trades_pnl': perf.last_30_pnl,
                'last_30_win_rate': perf.last_30_win_rate,
                'regime_performance': perf.regime_performance
            }
            
            total_trades += perf.total_trades
            total_pnl += perf.total_pnl
            total_fees += perf.total_fees
        
        summary['aggregate'] = {
            'total_trades': total_trades,
            'total_pnl': total_pnl,
            'total_fees': total_fees,
            'net_pnl': total_pnl - total_fees,
            'roi': (total_pnl - total_fees) / self.total_capital if self.total_capital > 0 else 0
        }
        
        return summary


def create_default_orchestrator(total_capital: float) -> StrategyOrchestrator:
    """
    Create orchestrator with default strategy configurations
    
    Args:
        total_capital: Total capital for allocation
        
    Returns:
        Configured StrategyOrchestrator
    """
    orchestrator = StrategyOrchestrator(total_capital)
    
    # Register v7.2 strategy (profitability focused)
    try:
        from nija_apex_strategy_v72_upgrade import NIJAApexStrategyV72
        
        v72_config = StrategyConfig(
            strategy_id="apex_v72",
            strategy_class=NIJAApexStrategyV72,
            weight=2.0,  # Higher weight - this is our best strategy
            state=StrategyState.ACTIVE,
            preferred_regimes=["trending", "ranging"],
            min_confidence_score=0.70
        )
        orchestrator.register_strategy(v72_config)
        logger.info("✅ Registered APEX v7.2 strategy")
    except ImportError:
        logger.warning("APEX v7.2 strategy not available")
    
    # Register v7.1 strategy (enhanced scoring)
    try:
        from nija_apex_strategy_v71 import NIJAApexStrategyV71
        
        v71_config = StrategyConfig(
            strategy_id="apex_v71",
            strategy_class=NIJAApexStrategyV71,
            weight=1.5,
            state=StrategyState.MONITORING,  # Start in monitoring mode
            preferred_regimes=["trending", "volatile"],
            min_confidence_score=0.65
        )
        orchestrator.register_strategy(v71_config)
        logger.info("✅ Registered APEX v7.1 strategy")
    except ImportError:
        logger.warning("APEX v7.1 strategy not available")
    
    return orchestrator
