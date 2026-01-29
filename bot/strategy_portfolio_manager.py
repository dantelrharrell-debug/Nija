"""
NIJA Strategy Portfolio Manager

Multi-strategy fund engine that coordinates multiple uncorrelated strategies,
performs portfolio optimization, and implements regime-based strategy switching.

Features:
- Multi-strategy coordination
- Strategy correlation analysis
- Dynamic capital allocation
- Regime-based strategy switching
- Portfolio optimization
- Risk-adjusted strategy weighting

Author: NIJA Trading Systems
Version: 1.0
Date: January 29, 2026
"""

import logging
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import json
from pathlib import Path

logger = logging.getLogger("nija.strategy_portfolio")


class TradingStrategy(Enum):
    """Available trading strategies"""
    APEX_RSI = "apex_rsi"  # Dual RSI strategy (current main strategy)
    TREND_FOLLOWING = "trend_following"  # Trend-following momentum
    MEAN_REVERSION = "mean_reversion"  # Mean reversion for ranging markets
    BREAKOUT = "breakout"  # Breakout strategy
    VOLATILITY_EXPANSION = "volatility_expansion"  # Trade volatility increases
    PAIRS_TRADING = "pairs_trading"  # Statistical arbitrage


class MarketRegime(Enum):
    """Market regime classifications"""
    BULL_TRENDING = "bull_trending"
    BEAR_TRENDING = "bear_trending"
    RANGING = "ranging"
    VOLATILE = "volatile"
    CRISIS = "crisis"


# Regime-Based Strategy Switching Matrix
REGIME_STRATEGY_MATRIX = {
    MarketRegime.BULL_TRENDING: {
        'primary': [TradingStrategy.TREND_FOLLOWING, TradingStrategy.BREAKOUT],
        'secondary': [TradingStrategy.APEX_RSI],
        'avoid': [TradingStrategy.MEAN_REVERSION]
    },
    MarketRegime.BEAR_TRENDING: {
        'primary': [TradingStrategy.TREND_FOLLOWING],  # With short bias
        'secondary': [TradingStrategy.VOLATILITY_EXPANSION],
        'avoid': [TradingStrategy.BREAKOUT]
    },
    MarketRegime.RANGING: {
        'primary': [TradingStrategy.MEAN_REVERSION, TradingStrategy.APEX_RSI],
        'secondary': [TradingStrategy.PAIRS_TRADING],
        'avoid': [TradingStrategy.TREND_FOLLOWING, TradingStrategy.BREAKOUT]
    },
    MarketRegime.VOLATILE: {
        'primary': [TradingStrategy.VOLATILITY_EXPANSION, TradingStrategy.BREAKOUT],
        'secondary': [TradingStrategy.APEX_RSI],
        'avoid': [TradingStrategy.MEAN_REVERSION]
    },
    MarketRegime.CRISIS: {
        'primary': [],  # Reduce all exposure
        'secondary': [TradingStrategy.VOLATILITY_EXPANSION],
        'avoid': [TradingStrategy.TREND_FOLLOWING, TradingStrategy.BREAKOUT, TradingStrategy.MEAN_REVERSION]
    }
}


@dataclass
class StrategyConfig:
    """Configuration for a single strategy"""
    name: str
    strategy_type: TradingStrategy
    enabled: bool = True
    min_allocation_pct: float = 0.0  # Minimum capital allocation
    max_allocation_pct: float = 100.0  # Maximum capital allocation
    preferred_regimes: List[MarketRegime] = field(default_factory=list)
    risk_multiplier: float = 1.0  # Risk adjustment factor


@dataclass
class StrategyPerformance:
    """Track performance of a single strategy"""
    strategy_name: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    current_allocation_pct: float = 0.0
    daily_returns: List[float] = field(default_factory=list)
    last_updated: datetime = field(default_factory=datetime.now)


@dataclass
class PortfolioAllocation:
    """Capital allocation across strategies"""
    allocations: Dict[str, float]  # strategy_name -> allocation_pct
    regime: MarketRegime
    timestamp: datetime
    total_capital: float


class StrategyPortfolioManager:
    """
    Manage multiple trading strategies as a portfolio
    
    Responsibilities:
    - Coordinate multiple uncorrelated strategies
    - Analyze strategy correlations
    - Optimize portfolio allocation
    - Switch strategies based on market regime
    - Track individual strategy performance
    - Rebalance capital allocation
    """
    
    def __init__(self, total_capital: float, data_dir: str = "./data/portfolio"):
        """
        Initialize strategy portfolio manager
        
        Args:
            total_capital: Total capital to manage
            data_dir: Directory to store portfolio data
        """
        self.total_capital = total_capital
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True, parents=True)
        
        # Strategy registry
        self.strategies: Dict[str, StrategyConfig] = {}
        self.performance: Dict[str, StrategyPerformance] = {}
        
        # Current state
        self.current_regime = MarketRegime.RANGING
        self.current_allocation: Optional[PortfolioAllocation] = None
        
        # Correlation matrix
        self.correlation_matrix: Optional[np.ndarray] = None
        self.strategy_names_ordered: List[str] = []
        
        # Initialize default strategies
        self._initialize_default_strategies()
        
        logger.info(f"✅ Strategy Portfolio Manager initialized with ${total_capital:,.2f}")
    
    def _initialize_default_strategies(self) -> None:
        """Initialize default strategy configurations"""
        # APEX RSI - Main strategy (works in most regimes)
        self.register_strategy(StrategyConfig(
            name="APEX_RSI",
            strategy_type=TradingStrategy.APEX_RSI,
            enabled=True,
            min_allocation_pct=30.0,
            max_allocation_pct=70.0,
            preferred_regimes=[
                MarketRegime.BULL_TRENDING,
                MarketRegime.RANGING,
                MarketRegime.VOLATILE
            ],
            risk_multiplier=1.0
        ))
        
        # Trend Following - Best in strong trends
        self.register_strategy(StrategyConfig(
            name="TREND_FOLLOWING",
            strategy_type=TradingStrategy.TREND_FOLLOWING,
            enabled=True,
            min_allocation_pct=0.0,
            max_allocation_pct=50.0,
            preferred_regimes=[
                MarketRegime.BULL_TRENDING,
                MarketRegime.BEAR_TRENDING
            ],
            risk_multiplier=1.2
        ))
        
        # Mean Reversion - Best in ranging markets
        self.register_strategy(StrategyConfig(
            name="MEAN_REVERSION",
            strategy_type=TradingStrategy.MEAN_REVERSION,
            enabled=True,
            min_allocation_pct=0.0,
            max_allocation_pct=40.0,
            preferred_regimes=[
                MarketRegime.RANGING
            ],
            risk_multiplier=0.8
        ))
        
        logger.info(f"Registered {len(self.strategies)} default strategies")
    
    def register_strategy(self, config: StrategyConfig) -> None:
        """
        Register a new strategy
        
        Args:
            config: Strategy configuration
        """
        self.strategies[config.name] = config
        
        # Initialize performance tracking
        if config.name not in self.performance:
            self.performance[config.name] = StrategyPerformance(
                strategy_name=config.name
            )
        
        logger.info(f"Registered strategy: {config.name} ({config.strategy_type.value})")
    
    def update_market_regime(self, regime: MarketRegime) -> None:
        """
        Update current market regime
        
        Args:
            regime: Current market regime
        """
        if regime != self.current_regime:
            logger.info(f"Market regime changed: {self.current_regime.value} → {regime.value}")
            self.current_regime = regime
            
            # Trigger reallocation based on new regime
            self.optimize_allocation()
    
    def calculate_correlation_matrix(self) -> np.ndarray:
        """
        Calculate correlation matrix between strategies
        
        Returns:
            Correlation matrix as numpy array
        """
        # Get enabled strategies with sufficient data
        strategies_with_data = [
            name for name, perf in self.performance.items()
            if len(perf.daily_returns) > 5 and self.strategies[name].enabled
        ]
        
        if len(strategies_with_data) < 2:
            # Not enough data for correlation
            return np.eye(len(strategies_with_data)) if strategies_with_data else np.array([[]])
        
        # Build returns matrix
        max_len = max(len(self.performance[name].daily_returns) for name in strategies_with_data)
        
        returns_matrix = []
        for name in strategies_with_data:
            returns = self.performance[name].daily_returns
            # Pad with zeros if needed
            padded = returns + [0.0] * (max_len - len(returns))
            returns_matrix.append(padded)
        
        returns_matrix = np.array(returns_matrix)
        
        # Calculate correlation
        self.correlation_matrix = np.corrcoef(returns_matrix)
        self.strategy_names_ordered = strategies_with_data
        
        logger.debug(f"Calculated correlation matrix for {len(strategies_with_data)} strategies")
        
        return self.correlation_matrix
    
    def optimize_allocation(self) -> PortfolioAllocation:
        """
        Optimize capital allocation across strategies
        
        Uses regime-based weighting and diversification principles
        
        Returns:
            Optimized portfolio allocation
        """
        enabled_strategies = {
            name: config for name, config in self.strategies.items()
            if config.enabled
        }
        
        if not enabled_strategies:
            logger.warning("No enabled strategies for allocation")
            return PortfolioAllocation(
                allocations={},
                regime=self.current_regime,
                timestamp=datetime.now(),
                total_capital=self.total_capital
            )
        
        # Calculate regime-based scores
        regime_scores = {}
        for name, config in enabled_strategies.items():
            # Base score from performance
            perf = self.performance[name]
            
            if perf.total_trades > 0:
                win_rate = perf.winning_trades / perf.total_trades
                performance_score = win_rate * (1 + perf.sharpe_ratio) - perf.max_drawdown_pct / 100
            else:
                performance_score = 0.5  # Neutral score for new strategies
            
            # Regime bonus
            regime_bonus = 1.5 if self.current_regime in config.preferred_regimes else 0.8
            
            # Risk adjustment
            risk_adjusted_score = performance_score * regime_bonus / config.risk_multiplier
            
            regime_scores[name] = max(risk_adjusted_score, 0.1)  # Minimum score
        
        # Normalize scores to allocations
        total_score = sum(regime_scores.values())
        raw_allocations = {
            name: (score / total_score * 100) if total_score > 0 else (100 / len(regime_scores))
            for name, score in regime_scores.items()
        }
        
        # Apply min/max constraints
        allocations = {}
        for name, allocation in raw_allocations.items():
            config = enabled_strategies[name]
            constrained = max(config.min_allocation_pct, min(config.max_allocation_pct, allocation))
            allocations[name] = constrained
        
        # Renormalize to 100%
        total_allocation = sum(allocations.values())
        if total_allocation > 0:
            allocations = {
                name: (alloc / total_allocation * 100)
                for name, alloc in allocations.items()
            }
        
        # Update current allocation
        self.current_allocation = PortfolioAllocation(
            allocations=allocations,
            regime=self.current_regime,
            timestamp=datetime.now(),
            total_capital=self.total_capital
        )
        
        # Update performance tracking
        for name, alloc_pct in allocations.items():
            self.performance[name].current_allocation_pct = alloc_pct
        
        logger.info(f"Optimized allocation for {self.current_regime.value} regime:")
        for name, alloc_pct in allocations.items():
            logger.info(f"  {name}: {alloc_pct:.1f}%")
        
        return self.current_allocation
    
    def get_strategy_capital(self, strategy_name: str) -> float:
        """
        Get allocated capital for a specific strategy
        
        Args:
            strategy_name: Name of the strategy
        
        Returns:
            Allocated capital amount
        """
        if not self.current_allocation:
            self.optimize_allocation()
        
        if strategy_name not in self.current_allocation.allocations:
            return 0.0
        
        allocation_pct = self.current_allocation.allocations[strategy_name]
        return self.total_capital * (allocation_pct / 100)
    
    def update_strategy_performance(self, strategy_name: str, 
                                    trade_result: Dict) -> None:
        """
        Update performance tracking for a strategy
        
        Args:
            strategy_name: Name of the strategy
            trade_result: Dictionary with trade results
        """
        if strategy_name not in self.performance:
            logger.warning(f"Unknown strategy: {strategy_name}")
            return
        
        perf = self.performance[strategy_name]
        
        # Update trade counts
        perf.total_trades += 1
        
        if trade_result.get('pnl', 0) > 0:
            perf.winning_trades += 1
        else:
            perf.losing_trades += 1
        
        # Update P&L
        perf.total_pnl += trade_result.get('pnl', 0)
        
        # Update daily returns if provided
        if 'return_pct' in trade_result:
            perf.daily_returns.append(trade_result['return_pct'])
        
        perf.last_updated = datetime.now()
        
        logger.debug(f"Updated performance for {strategy_name}: {perf.total_trades} trades, "
                    f"${perf.total_pnl:,.2f} P&L")
    
    def get_diversification_score(self) -> float:
        """
        Calculate portfolio diversification score (0-100)
        
        Higher score means better diversification
        
        Returns:
            Diversification score
        """
        if not self.current_allocation or len(self.current_allocation.allocations) < 2:
            return 0.0
        
        # Calculate correlation penalty
        if self.correlation_matrix is not None and len(self.correlation_matrix) > 1:
            # Average absolute correlation (excluding diagonal)
            n = len(self.correlation_matrix)
            off_diagonal = self.correlation_matrix[np.triu_indices(n, k=1)]
            avg_correlation = np.mean(np.abs(off_diagonal))
            
            # Lower correlation = better diversification
            correlation_score = (1 - avg_correlation) * 50
        else:
            correlation_score = 25  # Default mid-range score
        
        # Calculate allocation concentration (Herfindahl index)
        allocations = list(self.current_allocation.allocations.values())
        allocation_fractions = [a / 100 for a in allocations]
        herfindahl = sum(f ** 2 for f in allocation_fractions)
        
        # Perfect diversification: 1/n, Maximum concentration: 1.0
        n = len(allocations)
        perfect_herfindahl = 1 / n
        
        # Guard against division by zero for single strategy
        if n == 1:
            concentration_score = 0.0  # Single strategy = no diversification
        else:
            concentration_score = (1 - (herfindahl - perfect_herfindahl) / (1 - perfect_herfindahl)) * 50
        
        # Combine scores
        diversification_score = correlation_score + concentration_score
        
        return min(max(diversification_score, 0), 100)
    
    def get_portfolio_summary(self) -> Dict:
        """
        Get comprehensive portfolio summary
        
        Returns:
            Dictionary with portfolio metrics
        """
        if not self.current_allocation:
            self.optimize_allocation()
        
        # Calculate aggregate metrics
        total_trades = sum(perf.total_trades for perf in self.performance.values())
        total_pnl = sum(perf.total_pnl for perf in self.performance.values())
        
        # Weighted Sharpe ratio
        weighted_sharpe = 0.0
        if self.current_allocation:
            for name, alloc_pct in self.current_allocation.allocations.items():
                weight = alloc_pct / 100
                sharpe = self.performance[name].sharpe_ratio
                weighted_sharpe += weight * sharpe
        
        # Calculate correlations
        self.calculate_correlation_matrix()
        diversification_score = self.get_diversification_score()
        
        return {
            'total_capital': self.total_capital,
            'current_regime': self.current_regime.value,
            'active_strategies': len([s for s in self.strategies.values() if s.enabled]),
            'total_trades': total_trades,
            'total_pnl': total_pnl,
            'portfolio_sharpe': weighted_sharpe,
            'diversification_score': diversification_score,
            'allocations': self.current_allocation.allocations if self.current_allocation else {},
            'strategy_performance': {
                name: {
                    'total_trades': perf.total_trades,
                    'win_rate_pct': (perf.winning_trades / perf.total_trades * 100) if perf.total_trades > 0 else 0,
                    'total_pnl': perf.total_pnl,
                    'sharpe_ratio': perf.sharpe_ratio,
                    'allocation_pct': perf.current_allocation_pct
                }
                for name, perf in self.performance.items()
            }
        }
    
    def score_strategies(self) -> Dict[str, float]:
        """
        Score all strategies based on performance and risk metrics
        
        Returns:
            Dictionary mapping strategy names to scores (0-100)
        """
        scores = {}
        
        for name, config in self.strategies.items():
            if not config.enabled:
                scores[name] = 0.0
                continue
            
            perf = self.performance[name]
            
            # Performance component (40 points)
            win_rate_score = (perf.winning_trades / perf.total_trades * 40) if perf.total_trades > 0 else 20.0
            
            # Risk-adjusted return component (40 points)
            sharpe_score = min(perf.sharpe_ratio * 10, 40) if perf.sharpe_ratio > 0 else 0
            
            # Drawdown component (20 points) - inverse scoring
            dd_score = max(0, 20 - perf.max_drawdown_pct)
            
            # Total score
            total_score = win_rate_score + sharpe_score + dd_score
            
            scores[name] = min(total_score, 100.0)
        
        logger.info("Strategy Scores:")
        for name, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
            logger.info(f"  {name}: {score:.1f}/100")
        
        return scores
    
    def allocate_capital(self, scores: Optional[Dict[str, float]] = None) -> Dict[str, float]:
        """
        Allocate capital across strategies based on scores and constraints
        
        Args:
            scores: Strategy scores (will calculate if not provided)
        
        Returns:
            Dictionary mapping strategy names to capital amounts
        """
        if scores is None:
            scores = self.score_strategies()
        
        # Get current allocation
        if not self.current_allocation:
            self.optimize_allocation()
        
        allocations = {}
        for name, alloc_pct in self.current_allocation.allocations.items():
            capital = self.total_capital * (alloc_pct / 100)
            allocations[name] = capital
        
        logger.info("Capital Allocation:")
        for name, capital in sorted(allocations.items(), key=lambda x: x[1], reverse=True):
            logger.info(f"  {name}: ${capital:,.2f}")
        
        return allocations
    
    def rebalance_strategies(self, new_total_capital: Optional[float] = None) -> Dict[str, float]:
        """
        Rebalance strategies with updated capital and recalculate allocations
        
        Args:
            new_total_capital: Updated total capital (optional)
        
        Returns:
            Dictionary of new capital allocations
        """
        if new_total_capital is not None:
            self.total_capital = new_total_capital
        
        # Recalculate optimal allocation
        self.optimize_allocation()
        
        # Get new allocations
        new_allocations = self.allocate_capital()
        
        logger.info(f"✅ Rebalanced portfolio with total capital: ${self.total_capital:,.2f}")
        
        return new_allocations
    
    def optimize_diversification(self) -> Dict[str, any]:
        """
        Optimize portfolio for maximum diversification
        
        Returns:
            Dictionary with optimization results
        """
        # Calculate current correlation
        correlation_matrix = self.calculate_correlation_matrix()
        current_div_score = self.get_diversification_score()
        
        # Get current allocation
        if not self.current_allocation:
            self.optimize_allocation()
        
        # Simulate different allocations to maximize diversification
        best_allocation = self.current_allocation.allocations.copy()
        best_div_score = current_div_score
        
        # Try equal weight allocation
        enabled_strategies = [name for name, cfg in self.strategies.items() if cfg.enabled]
        if len(enabled_strategies) > 1:
            equal_weight = 100.0 / len(enabled_strategies)
            test_allocation = {name: equal_weight for name in enabled_strategies}
            
            # Temporarily update allocation to calculate score
            old_allocation = self.current_allocation
            self.current_allocation = PortfolioAllocation(
                allocations=test_allocation,
                regime=self.current_regime,
                timestamp=datetime.now(),
                total_capital=self.total_capital
            )
            
            test_div_score = self.get_diversification_score()
            
            if test_div_score > best_div_score:
                best_allocation = test_allocation
                best_div_score = test_div_score
            
            # Restore original allocation
            self.current_allocation = old_allocation
        
        logger.info(f"Diversification Optimization:")
        logger.info(f"  Current Score: {current_div_score:.1f}/100")
        logger.info(f"  Optimized Score: {best_div_score:.1f}/100")
        logger.info(f"  Improvement: {best_div_score - current_div_score:.1f} points")
        
        return {
            'current_diversification': current_div_score,
            'optimized_diversification': best_div_score,
            'improvement': best_div_score - current_div_score,
            'optimized_allocation': best_allocation,
            'correlation_matrix': correlation_matrix.tolist() if correlation_matrix.size > 0 else []
        }
    
    def get_regime_weights(self, regime: MarketRegime) -> Dict[str, float]:
        """
        Get regime-specific weights for strategies
        
        Args:
            regime: Current market regime
        
        Returns:
            Dictionary mapping strategy names to regime weights
        """
        regime_config = REGIME_STRATEGY_MATRIX.get(regime, {})
        
        weights = {}
        for name, config in self.strategies.items():
            strategy_type = config.strategy_type
            
            # Check strategy classification in regime
            if strategy_type in regime_config.get('primary', []):
                weights[name] = 1.5  # Boost primary strategies
            elif strategy_type in regime_config.get('secondary', []):
                weights[name] = 1.0  # Normal weight
            elif strategy_type in regime_config.get('avoid', []):
                weights[name] = 0.3  # Reduce avoided strategies
            else:
                weights[name] = 0.7  # Default reduced weight
        
        return weights
    
    def calculate_final_allocation(self, 
                                   base_weights: Dict[str, float],
                                   regime_weights: Dict[str, float],
                                   correlation_adjusted_weights: Optional[Dict[str, float]] = None) -> Dict[str, float]:
        """
        Calculate final capital allocation combining all factors
        
        Formula: capital = total_capital * strategy_weight * regime_weight * correlation_factor
        
        Args:
            base_weights: Base strategy weights (0-1)
            regime_weights: Regime-based weights
            correlation_adjusted_weights: Correlation-adjusted weights (optional)
        
        Returns:
            Dictionary mapping strategy names to capital amounts
        """
        final_allocations = {}
        
        for name in base_weights.keys():
            # Start with base weight
            weight = base_weights[name]
            
            # Apply regime weight
            regime_weight = regime_weights.get(name, 1.0)
            weight *= regime_weight
            
            # Apply correlation adjustment if provided
            if correlation_adjusted_weights:
                corr_factor = correlation_adjusted_weights.get(name, weight) / base_weights.get(name, 1.0)
                weight *= corr_factor
            
            final_allocations[name] = weight
        
        # Normalize to total capital
        total_weight = sum(final_allocations.values())
        if total_weight > 0:
            final_allocations = {
                name: (weight / total_weight) * self.total_capital
                for name, weight in final_allocations.items()
            }
        
        return final_allocations
        """Save portfolio state to disk"""
        state_file = self.data_dir / "portfolio_state.json"
        
        try:
            state = {
                'total_capital': self.total_capital,
                'current_regime': self.current_regime.value,
                'current_allocation': {
                    'allocations': self.current_allocation.allocations,
                    'regime': self.current_allocation.regime.value,
                    'timestamp': self.current_allocation.timestamp.isoformat(),
                    'total_capital': self.current_allocation.total_capital
                } if self.current_allocation else None,
                'performance': {
                    name: {
                        'strategy_name': perf.strategy_name,
                        'total_trades': perf.total_trades,
                        'winning_trades': perf.winning_trades,
                        'losing_trades': perf.losing_trades,
                        'total_pnl': perf.total_pnl,
                        'sharpe_ratio': perf.sharpe_ratio,
                        'max_drawdown_pct': perf.max_drawdown_pct,
                        'current_allocation_pct': perf.current_allocation_pct,
                        'daily_returns': perf.daily_returns[-100:],  # Keep last 100
                        'last_updated': perf.last_updated.isoformat()
                    }
                    for name, perf in self.performance.items()
                }
            }
            
            with open(state_file, 'w') as f:
                json.dump(state, f, indent=2)
            
            logger.debug("Saved portfolio state")
            
        except Exception as e:
            logger.error(f"Error saving portfolio state: {e}")


# Singleton instance
_portfolio_manager: Optional[StrategyPortfolioManager] = None


def get_portfolio_manager(total_capital: float = 1000.0, 
                          reset: bool = False) -> StrategyPortfolioManager:
    """
    Get or create the strategy portfolio manager singleton
    
    Args:
        total_capital: Total capital (only used on first creation)
        reset: Force reset and create new instance
    
    Returns:
        StrategyPortfolioManager instance
    """
    global _portfolio_manager
    
    if _portfolio_manager is None or reset:
        _portfolio_manager = StrategyPortfolioManager(total_capital)
    
    return _portfolio_manager
