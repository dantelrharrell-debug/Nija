"""
Strategy Swarm Intelligence
============================

Multi-strategy swarm that dynamically allocates capital based on:
- Individual strategy performance
- Strategy correlation and diversity
- Market regime adaptation
- Risk-adjusted returns

Author: NIJA Trading Systems
"""

import numpy as np
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging

from .evolution_config import SWARM_CONFIG

logger = logging.getLogger("nija.meta_ai.swarm")


@dataclass
class StrategyPerformance:
    """
    Tracks performance metrics for a strategy
    """
    strategy_id: str
    returns: List[float]
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 1.0
    max_drawdown: float = 0.0
    correlation_with_swarm: float = 0.0
    last_updated: datetime = None
    
    def __post_init__(self):
        if self.last_updated is None:
            self.last_updated = datetime.utcnow()


class StrategySwarm:
    """
    Multi-Strategy Swarm Intelligence
    
    Manages a swarm of strategies with:
    - Dynamic capital allocation based on performance
    - Diversity maintenance to avoid correlation
    - Adaptive rebalancing based on market conditions
    - Risk-adjusted position sizing
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize strategy swarm
        
        Args:
            config: Configuration dictionary (uses SWARM_CONFIG if None)
        """
        self.config = config or SWARM_CONFIG
        self.strategies: Dict[str, StrategyPerformance] = {}
        self.allocations: Dict[str, float] = {}  # Strategy ID -> allocation %
        self.last_rebalance: Optional[datetime] = None
        self.swarm_returns: List[float] = []
        
        logger.info(
            f"🐝 Strategy Swarm initialized: "
            f"max_strategies={self.config['num_strategies']}, "
            f"diversity_threshold={self.config['diversity_threshold']}"
        )
    
    def add_strategy(self, strategy_id: str, initial_performance: Dict = None):
        """
        Add a new strategy to the swarm
        
        Args:
            strategy_id: Unique strategy identifier
            initial_performance: Optional initial performance metrics
        """
        if len(self.strategies) >= self.config['num_strategies']:
            logger.warning(
                f"⚠️  Swarm at capacity ({self.config['num_strategies']}). "
                f"Cannot add {strategy_id}"
            )
            return False
        
        # Create performance tracker
        perf = StrategyPerformance(
            strategy_id=strategy_id,
            returns=[],
            sharpe_ratio=initial_performance.get('sharpe_ratio', 0.0) if initial_performance else 0.0,
            win_rate=initial_performance.get('win_rate', 0.5) if initial_performance else 0.5,
            profit_factor=initial_performance.get('profit_factor', 1.0) if initial_performance else 1.0,
        )
        
        self.strategies[strategy_id] = perf
        
        # Initial equal allocation
        self._rebalance_allocations()
        
        logger.info(f"✅ Added strategy {strategy_id} to swarm ({len(self.strategies)}/{self.config['num_strategies']})")
        return True
    
    def remove_strategy(self, strategy_id: str):
        """
        Remove a strategy from the swarm
        
        Args:
            strategy_id: Strategy to remove
        """
        if strategy_id in self.strategies:
            del self.strategies[strategy_id]
            if strategy_id in self.allocations:
                del self.allocations[strategy_id]
            
            # Rebalance remaining strategies
            self._rebalance_allocations()
            
            logger.info(f"❌ Removed strategy {strategy_id} from swarm")
    
    def update_strategy_performance(
        self,
        strategy_id: str,
        trade_return: float,
        metrics: Dict = None
    ):
        """
        Update strategy performance with new trade result
        
        Args:
            strategy_id: Strategy ID
            trade_return: Return from trade (e.g., 0.05 for 5% gain)
            metrics: Optional updated performance metrics
        """
        if strategy_id not in self.strategies:
            logger.warning(f"⚠️  Strategy {strategy_id} not in swarm")
            return
        
        perf = self.strategies[strategy_id]
        perf.returns.append(trade_return)
        perf.last_updated = datetime.utcnow()
        
        # Update metrics if provided
        if metrics:
            perf.sharpe_ratio = metrics.get('sharpe_ratio', perf.sharpe_ratio)
            perf.win_rate = metrics.get('win_rate', perf.win_rate)
            perf.profit_factor = metrics.get('profit_factor', perf.profit_factor)
            perf.max_drawdown = metrics.get('max_drawdown', perf.max_drawdown)
        
        # Update swarm returns
        if strategy_id in self.allocations:
            weighted_return = trade_return * self.allocations[strategy_id]
            self.swarm_returns.append(weighted_return)
        
        logger.debug(
            f"📊 Updated {strategy_id}: return={trade_return:.4f}, "
            f"Sharpe={perf.sharpe_ratio:.2f}"
        )
    
    def calculate_allocation_scores(self) -> Dict[str, float]:
        """
        Calculate allocation scores for each strategy
        
        Returns:
            Dict mapping strategy ID to allocation score
        """
        scores = {}
        
        for strategy_id, perf in self.strategies.items():
            if len(perf.returns) < 5:
                # Not enough data, use neutral score
                scores[strategy_id] = 0.5
                continue
            
            # Multi-factor scoring
            score = 0.0
            
            # Sharpe ratio (30% weight)
            sharpe_score = np.tanh(perf.sharpe_ratio / 2.0)  # Normalize to 0-1
            score += 0.30 * max(0, sharpe_score)
            
            # Win rate (20% weight)
            win_rate_score = (perf.win_rate - 0.4) / 0.3  # 40-70% maps to 0-1
            score += 0.20 * np.clip(win_rate_score, 0, 1)
            
            # Profit factor (20% weight)
            pf_score = (perf.profit_factor - 1.0) / 2.0  # PF 1-3 maps to 0-1
            score += 0.20 * np.clip(pf_score, 0, 1)
            
            # Recent performance (20% weight)
            recent_returns = perf.returns[-10:]
            avg_recent = np.mean(recent_returns) if recent_returns else 0
            recent_score = np.tanh(avg_recent * 100)  # Scale and normalize
            score += 0.20 * max(0, recent_score)
            
            # Diversity bonus (10% weight)
            # Lower correlation with swarm = higher score
            diversity_score = 1.0 - abs(perf.correlation_with_swarm)
            score += 0.10 * diversity_score
            
            scores[strategy_id] = np.clip(score, 0.0, 1.0)
        
        return scores
    
    def _calculate_strategy_correlations(self):
        """
        Update correlation of each strategy with the swarm
        """
        if len(self.swarm_returns) < 10:
            return  # Not enough data
        
        for strategy_id, perf in self.strategies.items():
            if len(perf.returns) < 10:
                perf.correlation_with_swarm = 0.0
                continue
            
            # Calculate correlation with swarm
            # Use last N returns (aligned)
            n = min(len(perf.returns), len(self.swarm_returns), 30)
            strategy_ret = perf.returns[-n:]
            swarm_ret = self.swarm_returns[-n:]
            
            if len(strategy_ret) == len(swarm_ret) and n > 1:
                correlation = np.corrcoef(strategy_ret, swarm_ret)[0, 1]
                perf.correlation_with_swarm = correlation
    
    def _rebalance_allocations(self):
        """
        Rebalance capital allocations across strategies
        """
        if not self.strategies:
            return
        
        # Update correlations
        self._calculate_strategy_correlations()
        
        # Calculate scores
        scores = self.calculate_allocation_scores()
        
        # Convert scores to allocations with constraints
        total_score = sum(scores.values())
        
        if total_score == 0:
            # Equal allocation if no performance data
            allocation_pct = 1.0 / len(self.strategies)
            self.allocations = {
                strategy_id: allocation_pct
                for strategy_id in self.strategies
            }
        else:
            # Proportional allocation with min/max constraints
            raw_allocations = {
                strategy_id: score / total_score
                for strategy_id, score in scores.items()
            }
            
            # Apply constraints
            self.allocations = {}
            for strategy_id, allocation in raw_allocations.items():
                constrained = np.clip(
                    allocation,
                    self.config['min_allocation'],
                    self.config['max_allocation']
                )
                self.allocations[strategy_id] = constrained
            
            # Normalize to sum to 1.0
            total_alloc = sum(self.allocations.values())
            if total_alloc > 0:
                self.allocations = {
                    sid: alloc / total_alloc
                    for sid, alloc in self.allocations.items()
                }
        
        self.last_rebalance = datetime.utcnow()
        
        logger.info(
            f"⚖️  Rebalanced swarm allocations: "
            f"{', '.join([f'{sid}: {alloc*100:.1f}%' for sid, alloc in self.allocations.items()])}"
        )
    
    def should_rebalance(self) -> bool:
        """
        Check if swarm should be rebalanced
        
        Returns:
            True if rebalance is needed
        """
        if self.last_rebalance is None:
            return True
        
        hours_since_rebalance = (
            datetime.utcnow() - self.last_rebalance
        ).total_seconds() / 3600
        
        return hours_since_rebalance >= self.config['rebalance_frequency']
    
    def get_strategy_allocation(self, strategy_id: str) -> float:
        """
        Get current allocation for a strategy
        
        Args:
            strategy_id: Strategy ID
            
        Returns:
            Allocation percentage (0-1)
        """
        if self.should_rebalance():
            self._rebalance_allocations()
        
        return self.allocations.get(strategy_id, 0.0)
    
    def get_swarm_stats(self) -> Dict:
        """
        Get swarm statistics
        
        Returns:
            Dictionary with swarm stats
        """
        if not self.strategies:
            return {
                'num_strategies': 0,
                'avg_sharpe': 0.0,
                'avg_win_rate': 0.0,
                'diversity': 0.0,
            }
        
        sharpes = [p.sharpe_ratio for p in self.strategies.values()]
        win_rates = [p.win_rate for p in self.strategies.values()]
        
        # Calculate diversity (average pairwise correlation difference)
        correlations = [
            abs(p.correlation_with_swarm)
            for p in self.strategies.values()
        ]
        diversity = 1.0 - np.mean(correlations) if correlations else 0.5
        
        return {
            'num_strategies': len(self.strategies),
            'avg_sharpe': np.mean(sharpes),
            'avg_win_rate': np.mean(win_rates),
            'diversity': diversity,
            'allocations': self.allocations.copy(),
            'total_returns': len(self.swarm_returns),
        }
