"""
NIJA Portfolio-Level Optimizer
==============================

Portfolio-wide optimization system that:
1. Scores and ranks all positions based on multiple factors
2. Optimizes portfolio composition for maximum risk-adjusted returns
3. Provides rebalancing recommendations
4. Integrates with correlation analysis for better diversification

Features:
- Multi-factor position scoring
- Portfolio efficiency metrics
- Risk-adjusted position weighting
- Automatic rebalancing recommendations
- Integration with existing PortfolioState

Author: NIJA Trading Systems
Version: 1.0
Date: January 29, 2026
"""

import logging
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger("nija.portfolio_optimizer")


@dataclass
class PositionScore:
    """Score for a single position in the portfolio"""
    symbol: str
    total_score: float  # Overall score (0-100)
    factors: Dict[str, float]  # Individual factor scores
    recommendation: str  # 'hold', 'increase', 'decrease', 'close'
    confidence: float  # Confidence in recommendation (0-1)
    reason: str  # Human-readable explanation


@dataclass
class OptimizationResult:
    """Result of portfolio optimization"""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    current_positions: Dict[str, PositionScore] = field(default_factory=dict)
    recommended_weights: Dict[str, float] = field(default_factory=dict)  # Symbol -> target weight
    rebalance_actions: List[Dict] = field(default_factory=list)  # List of actions to take
    efficiency_metrics: Dict = field(default_factory=dict)
    summary: str = ""


class PortfolioOptimizer:
    """
    Portfolio-level optimizer for NIJA trading system
    
    Optimizes entire portfolio composition rather than individual positions,
    considering correlations, risk factors, and opportunity quality.
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize Portfolio Optimizer
        
        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}
        
        # Scoring weights for different factors
        self.scoring_weights = {
            'profitability': self.config.get('profitability_weight', 0.30),  # Current P&L
            'trend_strength': self.config.get('trend_strength_weight', 0.20),  # Technical setup
            'risk_reward': self.config.get('risk_reward_weight', 0.20),  # Risk/reward ratio
            'correlation': self.config.get('correlation_weight', 0.15),  # Diversification value
            'momentum': self.config.get('momentum_weight', 0.15),  # Price momentum
        }
        
        # Optimization parameters
        self.max_position_weight = self.config.get('max_position_weight', 0.20)  # 20% max per position
        self.min_position_weight = self.config.get('min_position_weight', 0.02)  # 2% minimum
        self.target_position_count = self.config.get('target_position_count', 10)  # Optimal diversification
        self.rebalance_threshold = self.config.get('rebalance_threshold', 0.05)  # 5% deviation triggers rebalance
        
        logger.info("=" * 70)
        logger.info("📊 Portfolio Optimizer Initialized")
        logger.info("=" * 70)
        logger.info(f"Scoring Weights:")
        for factor, weight in self.scoring_weights.items():
            logger.info(f"  {factor}: {weight*100:.0f}%")
        logger.info(f"Target Positions: {self.target_position_count}")
        logger.info(f"Position Weight Range: {self.min_position_weight*100:.0f}%-{self.max_position_weight*100:.0f}%")
        logger.info("=" * 70)
    
    def score_position(
        self,
        symbol: str,
        position_data: Dict,
        market_data: Dict,
        correlation_matrix: Optional[pd.DataFrame] = None
    ) -> PositionScore:
        """
        Score a position based on multiple factors
        
        Args:
            symbol: Trading pair symbol
            position_data: Position info (pnl_pct, entry_price, current_price, etc.)
            market_data: Current market metrics (rsi, adx, atr, etc.)
            correlation_matrix: Optional correlation matrix for diversification scoring
            
        Returns:
            PositionScore object
        """
        scores = {}
        
        # Factor 1: Profitability (0-100)
        pnl_pct = position_data.get('pnl_pct', 0.0)
        if pnl_pct >= 5.0:
            scores['profitability'] = 100
        elif pnl_pct >= 2.0:
            scores['profitability'] = 80
        elif pnl_pct >= 0:
            scores['profitability'] = 60
        elif pnl_pct >= -2.0:
            scores['profitability'] = 40
        elif pnl_pct >= -5.0:
            scores['profitability'] = 20
        else:
            scores['profitability'] = 0
        
        # Factor 2: Trend Strength (0-100)
        adx = market_data.get('adx', 0)
        if adx >= 40:
            scores['trend_strength'] = 100
        elif adx >= 30:
            scores['trend_strength'] = 80
        elif adx >= 20:
            scores['trend_strength'] = 60
        elif adx >= 15:
            scores['trend_strength'] = 40
        else:
            scores['trend_strength'] = 20
        
        # Factor 3: Risk/Reward Ratio (0-100)
        current_price = position_data.get('current_price', 0)
        entry_price = position_data.get('entry_price', 0)
        stop_loss = position_data.get('stop_loss', entry_price * 0.95)  # Default 5% stop
        target_price = position_data.get('target_price', entry_price * 1.10)  # Default 10% target
        
        if current_price > 0 and stop_loss > 0:
            risk = abs(current_price - stop_loss)
            reward = abs(target_price - current_price)
            rr_ratio = reward / risk if risk > 0 else 0
            
            if rr_ratio >= 3.0:
                scores['risk_reward'] = 100
            elif rr_ratio >= 2.0:
                scores['risk_reward'] = 80
            elif rr_ratio >= 1.5:
                scores['risk_reward'] = 60
            elif rr_ratio >= 1.0:
                scores['risk_reward'] = 40
            else:
                scores['risk_reward'] = 20
        else:
            scores['risk_reward'] = 50  # Neutral if no data
        
        # Factor 4: Correlation/Diversification (0-100)
        if correlation_matrix is not None and symbol in correlation_matrix.index:
            # Lower average correlation = better diversification = higher score
            corr_values = correlation_matrix.loc[symbol].drop(symbol, errors='ignore')
            avg_corr = abs(corr_values).mean() if len(corr_values) > 0 else 0.5
            
            # Score inversely proportional to correlation
            scores['correlation'] = max(0, min(100, (1 - avg_corr) * 100))
        else:
            scores['correlation'] = 50  # Neutral if no correlation data
        
        # Factor 5: Momentum (0-100)
        rsi = market_data.get('rsi', 50)
        if 40 <= rsi <= 60:
            # Neutral RSI - moderate momentum
            scores['momentum'] = 70
        elif (30 <= rsi < 40) or (60 < rsi <= 70):
            # Mild oversold/overbought - good momentum
            scores['momentum'] = 85
        elif (20 <= rsi < 30) or (70 < rsi <= 80):
            # Moderate oversold/overbought - strong momentum
            scores['momentum'] = 60
        else:
            # Extreme levels - risky
            scores['momentum'] = 40
        
        # Calculate weighted total score
        total_score = sum(
            scores[factor] * self.scoring_weights[factor]
            for factor in scores
        )
        
        # Generate recommendation
        if total_score >= 75:
            recommendation = 'increase'
            confidence = 0.8
            reason = f"Strong position (score: {total_score:.0f}/100) - consider increasing allocation"
        elif total_score >= 60:
            recommendation = 'hold'
            confidence = 0.7
            reason = f"Good position (score: {total_score:.0f}/100) - maintain current allocation"
        elif total_score >= 40:
            recommendation = 'decrease'
            confidence = 0.6
            reason = f"Weak position (score: {total_score:.0f}/100) - consider reducing allocation"
        else:
            recommendation = 'close'
            confidence = 0.8
            reason = f"Poor position (score: {total_score:.0f}/100) - consider closing"
        
        return PositionScore(
            symbol=symbol,
            total_score=total_score,
            factors=scores,
            recommendation=recommendation,
            confidence=confidence,
            reason=reason
        )
    
    def optimize_portfolio(
        self,
        positions: List[Dict],
        market_data: Dict[str, Dict],
        total_equity: float,
        correlation_matrix: Optional[pd.DataFrame] = None
    ) -> OptimizationResult:
        """
        Optimize entire portfolio composition
        
        Args:
            positions: List of current positions
            market_data: Dictionary mapping symbol -> market metrics
            total_equity: Total portfolio equity
            correlation_matrix: Optional correlation matrix
            
        Returns:
            OptimizationResult with recommendations
        """
        logger.info("=" * 70)
        logger.info("🔬 Running Portfolio Optimization")
        logger.info("=" * 70)
        
        # Score all positions
        position_scores = {}
        for pos in positions:
            symbol = pos.get('symbol')
            market_metrics = market_data.get(symbol, {})
            
            score = self.score_position(
                symbol=symbol,
                position_data=pos,
                market_data=market_metrics,
                correlation_matrix=correlation_matrix
            )
            position_scores[symbol] = score
            
            logger.info(f"{symbol:12s} | Score: {score.total_score:5.1f}/100 | {score.recommendation.upper():8s} | {score.reason}")
        
        # Calculate optimal weights based on scores
        recommended_weights = self._calculate_optimal_weights(position_scores, total_equity)
        
        # Generate rebalancing actions
        rebalance_actions = self._generate_rebalance_actions(
            positions, position_scores, recommended_weights, total_equity
        )
        
        # Calculate efficiency metrics
        efficiency_metrics = self._calculate_efficiency_metrics(
            position_scores, positions, total_equity
        )
        
        # Generate summary
        summary = self._generate_summary(position_scores, rebalance_actions, efficiency_metrics)
        
        logger.info("=" * 70)
        logger.info(summary)
        logger.info("=" * 70)
        
        return OptimizationResult(
            current_positions=position_scores,
            recommended_weights=recommended_weights,
            rebalance_actions=rebalance_actions,
            efficiency_metrics=efficiency_metrics,
            summary=summary
        )
    
    def _calculate_optimal_weights(
        self,
        position_scores: Dict[str, PositionScore],
        total_equity: float
    ) -> Dict[str, float]:
        """
        Calculate optimal position weights based on scores
        
        Uses a score-weighted approach with min/max constraints
        """
        if not position_scores:
            return {}
        
        # Get scores for weighting
        scores = {symbol: score.total_score for symbol, score in position_scores.items()}
        total_score = sum(scores.values())
        
        if total_score <= 0:
            # Equal weight if all scores are zero
            equal_weight = 1.0 / len(position_scores)
            return {symbol: equal_weight for symbol in position_scores}
        
        # Calculate score-based weights
        raw_weights = {symbol: score / total_score for symbol, score in scores.items()}
        
        # Apply min/max constraints
        constrained_weights = {}
        for symbol, weight in raw_weights.items():
            constrained_weight = max(self.min_position_weight, min(self.max_position_weight, weight))
            constrained_weights[symbol] = constrained_weight
        
        # Normalize to sum to 1.0
        total_weight = sum(constrained_weights.values())
        if total_weight > 0:
            normalized_weights = {
                symbol: weight / total_weight
                for symbol, weight in constrained_weights.items()
            }
        else:
            normalized_weights = constrained_weights
        
        return normalized_weights
    
    def _generate_rebalance_actions(
        self,
        positions: List[Dict],
        position_scores: Dict[str, PositionScore],
        recommended_weights: Dict[str, float],
        total_equity: float
    ) -> List[Dict]:
        """Generate specific rebalancing actions"""
        actions = []
        
        # Calculate current weights
        current_weights = {}
        for pos in positions:
            symbol = pos.get('symbol')
            value = pos.get('market_value', 0)
            current_weights[symbol] = value / total_equity if total_equity > 0 else 0
        
        # Compare current vs recommended
        for symbol in recommended_weights:
            current_weight = current_weights.get(symbol, 0)
            target_weight = recommended_weights[symbol]
            weight_diff = target_weight - current_weight
            
            # Only rebalance if difference exceeds threshold
            if abs(weight_diff) >= self.rebalance_threshold:
                current_value = current_weight * total_equity
                target_value = target_weight * total_equity
                value_diff = target_value - current_value
                
                action = 'increase' if value_diff > 0 else 'decrease'
                
                actions.append({
                    'symbol': symbol,
                    'action': action,
                    'current_weight': current_weight,
                    'target_weight': target_weight,
                    'weight_change': weight_diff,
                    'current_value': current_value,
                    'target_value': target_value,
                    'value_change': value_diff,
                    'score': position_scores[symbol].total_score if symbol in position_scores else 0,
                    'priority': abs(weight_diff)  # Higher deviation = higher priority
                })
        
        # Sort by priority (highest first)
        actions.sort(key=lambda x: x['priority'], reverse=True)
        
        return actions
    
    def _calculate_efficiency_metrics(
        self,
        position_scores: Dict[str, PositionScore],
        positions: List[Dict],
        total_equity: float
    ) -> Dict:
        """Calculate portfolio efficiency metrics"""
        if not position_scores:
            return {}
        
        # Average position score
        avg_score = np.mean([score.total_score for score in position_scores.values()])
        
        # Score distribution
        scores_list = [score.total_score for score in position_scores.values()]
        score_std = np.std(scores_list) if len(scores_list) > 1 else 0
        
        # Position count
        position_count = len(positions)
        
        # Total unrealized P&L
        total_pnl = sum(pos.get('unrealized_pnl', 0) for pos in positions)
        total_pnl_pct = (total_pnl / total_equity * 100) if total_equity > 0 else 0
        
        # Recommendation distribution
        recommendations = [score.recommendation for score in position_scores.values()]
        rec_counts = {
            'increase': recommendations.count('increase'),
            'hold': recommendations.count('hold'),
            'decrease': recommendations.count('decrease'),
            'close': recommendations.count('close'),
        }
        
        return {
            'average_score': avg_score,
            'score_std': score_std,
            'position_count': position_count,
            'total_unrealized_pnl': total_pnl,
            'total_unrealized_pnl_pct': total_pnl_pct,
            'recommendations': rec_counts,
            'portfolio_quality': 'excellent' if avg_score >= 75 else 'good' if avg_score >= 60 else 'fair' if avg_score >= 40 else 'poor'
        }
    
    def _generate_summary(
        self,
        position_scores: Dict[str, PositionScore],
        rebalance_actions: List[Dict],
        efficiency_metrics: Dict
    ) -> str:
        """Generate human-readable summary"""
        lines = [
            "\n📊 PORTFOLIO OPTIMIZATION SUMMARY",
            "=" * 70,
            f"Portfolio Quality: {efficiency_metrics.get('portfolio_quality', 'unknown').upper()}",
            f"Average Position Score: {efficiency_metrics.get('average_score', 0):.1f}/100",
            f"Position Count: {efficiency_metrics.get('position_count', 0)}",
            f"Total Unrealized P&L: ${efficiency_metrics.get('total_unrealized_pnl', 0):.2f} ({efficiency_metrics.get('total_unrealized_pnl_pct', 0):.2f}%)",
            "",
            "Recommendations:",
        ]
        
        rec_counts = efficiency_metrics.get('recommendations', {})
        for rec_type, count in rec_counts.items():
            if count > 0:
                lines.append(f"  {rec_type.capitalize()}: {count} positions")
        
        if rebalance_actions:
            lines.append("")
            lines.append(f"Rebalancing Actions Required: {len(rebalance_actions)}")
            lines.append("Top 3 Priority Actions:")
            for i, action in enumerate(rebalance_actions[:3], 1):
                lines.append(
                    f"  {i}. {action['action'].upper()} {action['symbol']}: "
                    f"{action['current_weight']*100:.1f}% → {action['target_weight']*100:.1f}% "
                    f"(${action['value_change']:+.2f})"
                )
        else:
            lines.append("")
            lines.append("No rebalancing actions required - portfolio is well-optimized")
        
        return "\n".join(lines)


def create_portfolio_optimizer(config: Dict = None) -> PortfolioOptimizer:
    """
    Factory function to create PortfolioOptimizer instance
    
    Args:
        config: Optional configuration
        
    Returns:
        PortfolioOptimizer instance
    """
    return PortfolioOptimizer(config)


# Example usage
if __name__ == "__main__":
    import logging
    
    logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
    
    # Create optimizer
    optimizer = create_portfolio_optimizer()
    
    # Mock data
    positions = [
        {
            'symbol': 'BTC-USD',
            'quantity': 0.5,
            'entry_price': 40000,
            'current_price': 42000,
            'market_value': 21000,
            'unrealized_pnl': 1000,
            'pnl_pct': 5.0,
            'stop_loss': 38000,
            'target_price': 45000,
        },
        {
            'symbol': 'ETH-USD',
            'quantity': 10,
            'entry_price': 2000,
            'current_price': 1950,
            'market_value': 19500,
            'unrealized_pnl': -500,
            'pnl_pct': -2.5,
            'stop_loss': 1900,
            'target_price': 2200,
        },
    ]
    
    market_data = {
        'BTC-USD': {'adx': 35, 'rsi': 55, 'atr': 1500},
        'ETH-USD': {'adx': 25, 'rsi': 45, 'atr': 80},
    }
    
    # Run optimization
    result = optimizer.optimize_portfolio(
        positions=positions,
        market_data=market_data,
        total_equity=50000
    )
    
    print(result.summary)
