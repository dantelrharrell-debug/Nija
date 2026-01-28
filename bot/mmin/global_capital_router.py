"""
Global Capital Router
=====================

Intelligently routes capital across multiple markets based on:
- Market opportunity scoring
- Correlation-aware allocation
- Macro regime alignment
- Risk-adjusted returns
- Dynamic rebalancing
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import logging

from .mmin_config import CAPITAL_ALLOCATION_CONFIG, OPPORTUNITY_SCORING_CONFIG

logger = logging.getLogger("nija.mmin.capital")


class GlobalCapitalRouter:
    """
    Routes capital across multiple markets intelligently
    
    Features:
    - Multi-market opportunity scoring
    - Correlation-aware diversification
    - Macro regime-based allocation
    - Dynamic rebalancing
    - Risk-adjusted capital allocation
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize global capital router
        
        Args:
            config: Optional configuration dictionary
        """
        self.config = config or CAPITAL_ALLOCATION_CONFIG
        self.scoring_config = OPPORTUNITY_SCORING_CONFIG
        
        self.enabled = self.config['enabled']
        self.strategy = self.config['allocation_strategy']
        self.min_allocation = self.config['min_allocation_per_market']
        self.max_allocation = self.config['max_allocation_per_market']
        
        # Current allocation
        self.current_allocation: Dict[str, float] = {}
        
        # Performance tracking
        self.market_performance: Dict[str, Dict] = {}
        
        logger.info(f"GlobalCapitalRouter initialized (strategy={self.strategy})")
    
    def calculate_allocation(self, market_metrics: Dict[str, Dict],
                           correlations: pd.DataFrame = None,
                           macro_regime: str = None,
                           total_capital: float = 100000.0) -> Dict[str, float]:
        """
        Calculate optimal capital allocation across markets
        
        Args:
            market_metrics: Dictionary of metrics per market
            correlations: Correlation matrix between markets
            macro_regime: Current macro regime
            total_capital: Total capital to allocate
            
        Returns:
            Dictionary mapping market to capital allocation
        """
        if self.strategy == 'fixed':
            return self._fixed_allocation(total_capital)
        elif self.strategy == 'adaptive':
            return self._adaptive_allocation(market_metrics, correlations, 
                                            macro_regime, total_capital)
        elif self.strategy == 'aggressive':
            return self._aggressive_allocation(market_metrics, total_capital)
        else:
            # Default to balanced
            return self._balanced_allocation(market_metrics, total_capital)
    
    def _fixed_allocation(self, total_capital: float) -> Dict[str, float]:
        """Fixed allocation strategy"""
        allocation = {}
        fixed_percentages = self.config['fixed_allocation']
        
        for market, percentage in fixed_percentages.items():
            allocation[market] = total_capital * percentage
        
        logger.debug(f"Fixed allocation: {allocation}")
        return allocation
    
    def _adaptive_allocation(self, market_metrics: Dict[str, Dict],
                           correlations: pd.DataFrame,
                           macro_regime: str,
                           total_capital: float) -> Dict[str, float]:
        """
        Adaptive allocation based on market conditions
        
        Considers:
        - Market performance metrics
        - Correlation diversification
        - Macro regime alignment
        """
        # Score each market
        market_scores = self._score_markets(market_metrics, macro_regime)
        
        # Adjust for correlation (penalize highly correlated markets)
        if correlations is not None:
            market_scores = self._adjust_for_correlation(market_scores, correlations)
        
        # Normalize scores to percentages
        total_score = sum(market_scores.values())
        if total_score == 0:
            return self._balanced_allocation(market_metrics, total_capital)
        
        raw_allocation = {
            market: (score / total_score) 
            for market, score in market_scores.items()
        }
        
        # Apply min/max constraints
        allocation = self._apply_constraints(raw_allocation, total_capital)
        
        logger.info(f"Adaptive allocation: {allocation}")
        return allocation
    
    def _aggressive_allocation(self, market_metrics: Dict[str, Dict],
                              total_capital: float) -> Dict[str, float]:
        """Aggressive allocation - concentrate in top performers"""
        # Score markets
        market_scores = {}
        for market, metrics in market_metrics.items():
            # Focus on profit factor and win rate
            pf = metrics.get('profit_factor', 1.0)
            wr = metrics.get('win_rate', 0.5)
            sharpe = metrics.get('sharpe_ratio', 0.0)
            
            score = (pf * 0.4) + (wr * 0.3) + (sharpe * 0.3)
            market_scores[market] = score
        
        # Sort and take top 3
        sorted_markets = sorted(market_scores.items(), key=lambda x: x[1], reverse=True)
        top_markets = sorted_markets[:3]
        
        # Allocate aggressively to top performers
        allocation = {}
        percentages = [0.5, 0.3, 0.2]  # 50%, 30%, 20%
        
        for i, (market, score) in enumerate(top_markets):
            allocation[market] = total_capital * percentages[i]
        
        logger.info(f"Aggressive allocation to top 3: {allocation}")
        return allocation
    
    def _balanced_allocation(self, market_metrics: Dict[str, Dict],
                           total_capital: float) -> Dict[str, float]:
        """Balanced allocation across all markets"""
        n_markets = len(market_metrics)
        if n_markets == 0:
            return {}
        
        equal_share = total_capital / n_markets
        allocation = {market: equal_share for market in market_metrics.keys()}
        
        logger.debug(f"Balanced allocation: {allocation}")
        return allocation
    
    def _score_markets(self, market_metrics: Dict[str, Dict],
                      macro_regime: str = None) -> Dict[str, float]:
        """Score markets based on multiple factors"""
        weights = self.config['allocation_metrics']
        scores = {}
        
        for market, metrics in market_metrics.items():
            # Base score from metrics
            sharpe = metrics.get('sharpe_ratio', 0.0)
            win_rate = metrics.get('win_rate', 0.5)
            profit_factor = metrics.get('profit_factor', 1.0)
            opportunities = metrics.get('opportunity_count', 1)
            
            # Normalize metrics
            sharpe_score = min(sharpe / 3.0, 1.0)  # 3.0 is excellent Sharpe
            wr_score = win_rate
            pf_score = min((profit_factor - 1.0) / 2.0, 1.0)  # 3.0 PF = max score
            opp_score = min(opportunities / 10.0, 1.0)  # 10+ opportunities = max
            
            # Weighted score
            score = (
                sharpe_score * weights['sharpe_ratio_weight'] +
                wr_score * weights['win_rate_weight'] +
                pf_score * weights['profit_factor_weight'] +
                opp_score * weights['opportunity_count_weight']
            )
            
            # Adjust for macro regime
            if macro_regime:
                regime_adjustment = self._get_regime_adjustment(market, macro_regime)
                score *= regime_adjustment
            
            scores[market] = max(score, 0.01)  # Minimum score
        
        return scores
    
    def _get_regime_adjustment(self, market: str, regime: str) -> float:
        """Get adjustment factor based on macro regime"""
        # Regime-market alignment
        regime_preferences = {
            'risk_on': {'crypto': 1.5, 'equities': 1.3, 'forex': 0.8, 'bonds': 0.5},
            'risk_off': {'crypto': 0.5, 'equities': 0.6, 'forex': 1.2, 'bonds': 1.5},
            'inflation': {'commodities': 1.5, 'crypto': 1.2, 'bonds': 0.5},
            'deflation': {'bonds': 1.5, 'forex': 1.2, 'commodities': 0.5},
            'growth': {'equities': 1.4, 'crypto': 1.3, 'commodities': 1.1},
            'recession': {'bonds': 1.5, 'forex': 1.2, 'equities': 0.5, 'crypto': 0.4},
        }
        
        preferences = regime_preferences.get(regime, {})
        return preferences.get(market, 1.0)
    
    def _adjust_for_correlation(self, scores: Dict[str, float],
                               correlations: pd.DataFrame) -> Dict[str, float]:
        """Adjust scores to favor diversification"""
        adjusted_scores = scores.copy()
        
        for market in scores.keys():
            if market not in correlations.index:
                continue
            
            # Calculate average correlation with other markets
            other_markets = [m for m in scores.keys() if m != market and m in correlations.columns]
            if not other_markets:
                continue
            
            avg_corr = correlations.loc[market, other_markets].abs().mean()
            
            # Penalize high correlation (reduce score for highly correlated markets)
            # Low correlation (0.0) → no penalty (1.0x)
            # High correlation (1.0) → 50% penalty (0.5x)
            diversification_bonus = 1.0 - (0.5 * avg_corr)
            adjusted_scores[market] *= diversification_bonus
        
        return adjusted_scores
    
    def _apply_constraints(self, raw_allocation: Dict[str, float],
                          total_capital: float) -> Dict[str, float]:
        """Apply min/max allocation constraints"""
        allocation = {}
        
        for market, percentage in raw_allocation.items():
            # Apply constraints
            percentage = max(percentage, self.min_allocation)
            percentage = min(percentage, self.max_allocation)
            allocation[market] = percentage * total_capital
        
        # Renormalize to ensure total = total_capital
        total_allocated = sum(allocation.values())
        if total_allocated > 0:
            scale_factor = total_capital / total_allocated
            allocation = {market: capital * scale_factor 
                         for market, capital in allocation.items()}
        
        return allocation
    
    def suggest_rebalance(self, current_allocation: Dict[str, float],
                         target_allocation: Dict[str, float],
                         threshold: float = 0.05) -> Dict[str, float]:
        """
        Suggest rebalancing moves
        
        Args:
            current_allocation: Current capital allocation
            target_allocation: Target allocation
            threshold: Minimum deviation to trigger rebalance (5% default)
            
        Returns:
            Dictionary of rebalancing moves (positive = add capital, negative = remove)
        """
        rebalance_moves = {}
        
        all_markets = set(current_allocation.keys()) | set(target_allocation.keys())
        
        for market in all_markets:
            current = current_allocation.get(market, 0.0)
            target = target_allocation.get(market, 0.0)
            
            deviation = target - current
            deviation_pct = abs(deviation) / max(current, target, 1.0)
            
            if deviation_pct >= threshold:
                rebalance_moves[market] = deviation
        
        if rebalance_moves:
            logger.info(f"Rebalancing suggested for {len(rebalance_moves)} markets")
        
        return rebalance_moves
    
    def score_opportunity(self, opportunity: Dict) -> float:
        """
        Score a trading opportunity
        
        Args:
            opportunity: Dictionary with opportunity details
            
        Returns:
            Score from 0-1
        """
        factors = self.scoring_config['scoring_factors']
        
        # Extract metrics
        technical_score = opportunity.get('technical_setup', 0.5)
        regime_score = opportunity.get('regime_alignment', 0.5)
        correlation_score = opportunity.get('correlation_support', 0.5)
        volume_score = opportunity.get('volume_profile', 0.5)
        risk_reward = opportunity.get('risk_reward_ratio', 1.0)
        
        # Normalize risk/reward (2.0 is good, 3.0+ is excellent)
        rr_score = min(risk_reward / 3.0, 1.0)
        
        # Weighted score
        total_score = (
            technical_score * factors['technical_setup'] +
            regime_score * factors['regime_alignment'] +
            correlation_score * factors['correlation_support'] +
            volume_score * factors['volume_profile'] +
            rr_score * factors['risk_reward_ratio']
        )
        
        return total_score
    
    def update_market_performance(self, market: str, metrics: Dict):
        """Update performance metrics for a market"""
        self.market_performance[market] = {
            **metrics,
            'last_updated': datetime.now(),
        }
    
    def get_allocation_stats(self) -> Dict:
        """Get allocation statistics"""
        return {
            'current_allocation': self.current_allocation,
            'strategy': self.strategy,
            'total_markets': len(self.market_performance),
            'performance_metrics': self.market_performance,
        }
