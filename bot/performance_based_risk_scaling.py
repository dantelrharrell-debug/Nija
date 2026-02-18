"""
NIJA Performance-Based Risk Scaling
====================================

Dynamically adjusts risk exposure based on recent trading performance.
Increases position sizes during winning periods, decreases during losses.

Key Features:
- Multiple timeframe performance tracking (daily, weekly, monthly)
- Sharpe ratio-based scaling
- Win rate and profit factor analysis
- Adaptive confidence scoring
- Performance-based multipliers
- Drawdown-aware scaling (prevents over-sizing in recovery)

Philosophy:
- "Let winners run" by scaling up during profitable periods
- "Cut losses" by scaling down during unprofitable periods
- Prevent overconfidence with maximum scale limits
- Maintain discipline with minimum scale floors

Author: NIJA Trading Systems
Version: 1.0
Date: February 18, 2026
"""

import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import statistics

logger = logging.getLogger("nija.performance_based_risk_scaling")


class PerformanceLevel(Enum):
    """Performance levels for risk scaling"""
    POOR = "poor"  # Consistent losses
    WEAK = "weak"  # Below average
    AVERAGE = "average"  # Meeting expectations
    STRONG = "strong"  # Above average
    EXCELLENT = "excellent"  # Outstanding performance


@dataclass
class PerformanceMetrics:
    """Performance metrics for risk scaling"""
    # Returns
    daily_return: float = 0.0
    weekly_return: float = 0.0
    monthly_return: float = 0.0
    
    # Risk-adjusted returns
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    
    # Win statistics
    win_rate: float = 0.5
    profit_factor: float = 1.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    
    # Streak information
    current_streak: int = 0  # Positive for wins, negative for losses
    max_winning_streak: int = 0
    max_losing_streak: int = 0
    
    # Drawdown
    current_drawdown_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    
    # Confidence
    confidence_score: float = 0.5  # 0-1 scale
    
    def __str__(self):
        return (
            f"Return: {self.monthly_return:.2%} | "
            f"Sharpe: {self.sharpe_ratio:.2f} | "
            f"Win Rate: {self.win_rate:.1%} | "
            f"PF: {self.profit_factor:.2f}"
        )


@dataclass
class ScalingConfig:
    """Configuration for performance-based scaling"""
    # Scale multiplier ranges
    min_scale: float = 0.5  # Minimum scale during poor performance
    max_scale: float = 1.5  # Maximum scale during excellent performance
    base_scale: float = 1.0  # Default scale
    
    # Performance thresholds for scaling up
    scale_up_sharpe: float = 1.5  # Sharpe ratio to scale up
    scale_up_win_rate: float = 0.60  # Win rate to scale up
    scale_up_monthly_return: float = 0.10  # 10% monthly return to scale up
    
    # Performance thresholds for scaling down
    scale_down_sharpe: float = 0.5  # Sharpe ratio to scale down
    scale_down_win_rate: float = 0.40  # Win rate to scale down
    scale_down_monthly_return: float = -0.05  # -5% monthly return to scale down
    
    # Streak modifiers
    winning_streak_bonus: float = 0.05  # +5% per winning streak
    losing_streak_penalty: float = 0.10  # -10% per losing streak
    max_streak_impact: float = 0.30  # Max 30% impact from streaks
    
    # Drawdown limits
    max_drawdown_for_scaling: float = 10.0  # Don't scale up if DD > 10%
    drawdown_scale_penalty: float = 0.05  # -5% scale per 1% DD
    
    # Confidence weighting
    use_confidence_weighting: bool = True
    confidence_weight: float = 0.3  # 30% weight to confidence score


@dataclass
class ScalingResult:
    """Result of performance-based scaling calculation"""
    base_size: float
    scaled_size: float
    scale_factor: float
    performance_level: PerformanceLevel
    reasoning: List[str] = field(default_factory=list)
    metrics_used: Dict = field(default_factory=dict)
    
    def get_summary(self) -> str:
        """Get human-readable summary"""
        change_pct = (self.scale_factor - 1.0) * 100
        direction = "↑" if change_pct > 0 else "↓" if change_pct < 0 else "→"
        
        summary = (
            f"{direction} Scale: {self.scale_factor:.2%} | "
            f"Level: {self.performance_level.value.upper()} | "
            f"${self.base_size:.2f} → ${self.scaled_size:.2f}"
        )
        
        if self.reasoning:
            summary += f"\nReasons: {' | '.join(self.reasoning)}"
        
        return summary


class PerformanceBasedRiskScaling:
    """
    Dynamically scales position sizes based on trading performance.
    
    Methodology:
    1. Track performance across multiple timeframes
    2. Calculate risk-adjusted returns (Sharpe, Sortino)
    3. Analyze win statistics and streaks
    4. Determine performance level
    5. Calculate appropriate scale factor
    6. Apply drawdown and confidence adjustments
    
    Scale factors range from 0.5x (poor performance) to 1.5x (excellent).
    """
    
    def __init__(self, config: Optional[ScalingConfig] = None):
        """
        Initialize performance-based risk scaling.
        
        Args:
            config: Optional scaling configuration
        """
        self.config = config or ScalingConfig()
        
        # Performance tracking
        self.metrics = PerformanceMetrics()
        self.trade_history: List[Dict] = []
        
        logger.info("=" * 70)
        logger.info("📊 Performance-Based Risk Scaling Initialized")
        logger.info("=" * 70)
        logger.info(f"Scale Range: {self.config.min_scale:.1%} - {self.config.max_scale:.1%}")
        logger.info(f"Scale Up Thresholds: Sharpe>{self.config.scale_up_sharpe:.2f}, "
                   f"WinRate>{self.config.scale_up_win_rate:.1%}, "
                   f"Return>{self.config.scale_up_monthly_return:.1%}")
        logger.info(f"Scale Down Thresholds: Sharpe<{self.config.scale_down_sharpe:.2f}, "
                   f"WinRate<{self.config.scale_down_win_rate:.1%}, "
                   f"Return<{self.config.scale_down_monthly_return:.1%}")
        logger.info("=" * 70)
    
    def calculate_scale_factor(
        self,
        base_position_size: float,
        current_metrics: Optional[PerformanceMetrics] = None
    ) -> ScalingResult:
        """
        Calculate scaled position size based on performance.
        
        Args:
            base_position_size: Base position size before scaling
            current_metrics: Optional current metrics (uses internal if not provided)
            
        Returns:
            ScalingResult with scaled size and reasoning
        """
        # Use provided metrics or internal
        metrics = current_metrics or self.metrics
        
        # Start with base scale
        scale_factor = self.config.base_scale
        reasoning = []
        
        # 1. Sharpe Ratio Contribution
        sharpe_contribution = self._calculate_sharpe_contribution(metrics.sharpe_ratio)
        scale_factor *= sharpe_contribution
        if sharpe_contribution != 1.0:
            reasoning.append(f"Sharpe {metrics.sharpe_ratio:.2f} → {sharpe_contribution:.2%}")
        
        # 2. Win Rate Contribution
        win_rate_contribution = self._calculate_win_rate_contribution(metrics.win_rate)
        scale_factor *= win_rate_contribution
        if win_rate_contribution != 1.0:
            reasoning.append(f"Win rate {metrics.win_rate:.1%} → {win_rate_contribution:.2%}")
        
        # 3. Monthly Return Contribution
        return_contribution = self._calculate_return_contribution(metrics.monthly_return)
        scale_factor *= return_contribution
        if return_contribution != 1.0:
            reasoning.append(f"Monthly return {metrics.monthly_return:.1%} → {return_contribution:.2%}")
        
        # 4. Profit Factor Contribution
        pf_contribution = self._calculate_profit_factor_contribution(metrics.profit_factor)
        scale_factor *= pf_contribution
        if pf_contribution != 1.0:
            reasoning.append(f"Profit factor {metrics.profit_factor:.2f} → {pf_contribution:.2%}")
        
        # 5. Streak Adjustment
        streak_adjustment = self._calculate_streak_adjustment(metrics.current_streak)
        scale_factor *= streak_adjustment
        if streak_adjustment != 1.0:
            streak_type = "win" if metrics.current_streak > 0 else "loss"
            reasoning.append(f"{abs(metrics.current_streak)} {streak_type} streak → {streak_adjustment:.2%}")
        
        # 6. Drawdown Penalty
        if metrics.current_drawdown_pct > 0:
            dd_penalty = self._calculate_drawdown_penalty(metrics.current_drawdown_pct)
            scale_factor *= dd_penalty
            reasoning.append(f"Drawdown {metrics.current_drawdown_pct:.1f}% → {dd_penalty:.2%}")
        
        # 7. Confidence Weighting
        if self.config.use_confidence_weighting:
            confidence_factor = 1.0 + ((metrics.confidence_score - 0.5) * self.config.confidence_weight)
            scale_factor *= confidence_factor
            reasoning.append(f"Confidence {metrics.confidence_score:.2f} → {confidence_factor:.2%}")
        
        # Apply bounds
        scale_factor = max(self.config.min_scale, min(self.config.max_scale, scale_factor))
        
        # Calculate scaled size
        scaled_size = base_position_size * scale_factor
        
        # Determine performance level
        performance_level = self._classify_performance_level(metrics)
        
        # Create result
        result = ScalingResult(
            base_size=base_position_size,
            scaled_size=scaled_size,
            scale_factor=scale_factor,
            performance_level=performance_level,
            reasoning=reasoning,
            metrics_used={
                'sharpe_ratio': metrics.sharpe_ratio,
                'win_rate': metrics.win_rate,
                'monthly_return': metrics.monthly_return,
                'profit_factor': metrics.profit_factor,
                'current_streak': metrics.current_streak,
                'drawdown_pct': metrics.current_drawdown_pct,
                'confidence_score': metrics.confidence_score
            }
        )
        
        logger.debug(result.get_summary())
        
        return result
    
    def _calculate_sharpe_contribution(self, sharpe_ratio: float) -> float:
        """Calculate scale contribution from Sharpe ratio"""
        if sharpe_ratio >= self.config.scale_up_sharpe:
            # Excellent Sharpe - scale up
            excess = sharpe_ratio - self.config.scale_up_sharpe
            return min(1.3, 1.0 + (excess * 0.15))  # Up to 30% bonus
        elif sharpe_ratio <= self.config.scale_down_sharpe:
            # Poor Sharpe - scale down
            deficit = self.config.scale_down_sharpe - sharpe_ratio
            return max(0.7, 1.0 - (deficit * 0.15))  # Up to 30% penalty
        else:
            # Average Sharpe - neutral
            return 1.0
    
    def _calculate_win_rate_contribution(self, win_rate: float) -> float:
        """Calculate scale contribution from win rate"""
        if win_rate >= self.config.scale_up_win_rate:
            # High win rate - scale up
            excess = win_rate - self.config.scale_up_win_rate
            return min(1.25, 1.0 + (excess * 1.0))  # Up to 25% bonus
        elif win_rate <= self.config.scale_down_win_rate:
            # Low win rate - scale down
            deficit = self.config.scale_down_win_rate - win_rate
            return max(0.75, 1.0 - (deficit * 1.0))  # Up to 25% penalty
        else:
            # Average win rate - neutral
            return 1.0
    
    def _calculate_return_contribution(self, monthly_return: float) -> float:
        """Calculate scale contribution from monthly return"""
        if monthly_return >= self.config.scale_up_monthly_return:
            # Strong returns - scale up
            excess = monthly_return - self.config.scale_up_monthly_return
            return min(1.4, 1.0 + (excess * 2.0))  # Up to 40% bonus
        elif monthly_return <= self.config.scale_down_monthly_return:
            # Negative returns - scale down
            deficit = abs(monthly_return - self.config.scale_down_monthly_return)
            return max(0.6, 1.0 - (deficit * 2.0))  # Up to 40% penalty
        else:
            # Average returns - neutral
            return 1.0
    
    def _calculate_profit_factor_contribution(self, profit_factor: float) -> float:
        """Calculate scale contribution from profit factor"""
        if profit_factor >= 2.0:
            # Excellent profit factor - scale up
            return min(1.2, 1.0 + ((profit_factor - 2.0) * 0.1))
        elif profit_factor <= 1.0:
            # Poor profit factor - scale down
            return max(0.8, profit_factor)
        else:
            # Average - neutral
            return 1.0
    
    def _calculate_streak_adjustment(self, current_streak: int) -> float:
        """Calculate adjustment based on current streak"""
        if current_streak > 0:
            # Winning streak - modest bonus
            bonus = min(
                self.config.max_streak_impact,
                current_streak * self.config.winning_streak_bonus
            )
            return 1.0 + bonus
        elif current_streak < 0:
            # Losing streak - significant penalty
            penalty = min(
                self.config.max_streak_impact,
                abs(current_streak) * self.config.losing_streak_penalty
            )
            return 1.0 - penalty
        else:
            return 1.0
    
    def _calculate_drawdown_penalty(self, drawdown_pct: float) -> float:
        """Calculate penalty based on drawdown"""
        if drawdown_pct >= self.config.max_drawdown_for_scaling:
            # Significant drawdown - don't scale up
            penalty = min(0.5, drawdown_pct * self.config.drawdown_scale_penalty)
            return max(0.5, 1.0 - penalty)
        else:
            # Minor drawdown - small penalty
            penalty = drawdown_pct * (self.config.drawdown_scale_penalty / 2)
            return 1.0 - penalty
    
    def _classify_performance_level(self, metrics: PerformanceMetrics) -> PerformanceLevel:
        """Classify overall performance level"""
        score = 0
        
        # Sharpe ratio
        if metrics.sharpe_ratio >= 2.0:
            score += 2
        elif metrics.sharpe_ratio >= 1.5:
            score += 1
        elif metrics.sharpe_ratio < 0.5:
            score -= 1
        
        # Win rate
        if metrics.win_rate >= 0.65:
            score += 2
        elif metrics.win_rate >= 0.55:
            score += 1
        elif metrics.win_rate < 0.45:
            score -= 1
        
        # Monthly return
        if metrics.monthly_return >= 0.15:
            score += 2
        elif metrics.monthly_return >= 0.08:
            score += 1
        elif metrics.monthly_return < 0:
            score -= 1
        
        # Profit factor
        if metrics.profit_factor >= 2.5:
            score += 1
        elif metrics.profit_factor < 1.0:
            score -= 2
        
        # Classify based on score
        if score >= 5:
            return PerformanceLevel.EXCELLENT
        elif score >= 2:
            return PerformanceLevel.STRONG
        elif score >= -1:
            return PerformanceLevel.AVERAGE
        elif score >= -3:
            return PerformanceLevel.WEAK
        else:
            return PerformanceLevel.POOR
    
    def update_metrics(self, metrics: PerformanceMetrics):
        """
        Update performance metrics.
        
        Args:
            metrics: New performance metrics
        """
        self.metrics = metrics
        logger.debug(f"📊 Metrics updated: {metrics}")
    
    def record_trade(
        self,
        profit_loss: float,
        return_pct: float,
        was_win: bool
    ):
        """
        Record a trade for performance tracking.
        
        Args:
            profit_loss: Dollar P&L
            return_pct: Return percentage
            was_win: True if profitable
        """
        trade = {
            'timestamp': datetime.now().isoformat(),
            'profit_loss': profit_loss,
            'return_pct': return_pct,
            'was_win': was_win
        }
        
        self.trade_history.append(trade)
        
        # Update streak
        if was_win:
            if self.metrics.current_streak >= 0:
                self.metrics.current_streak += 1
            else:
                self.metrics.current_streak = 1
            self.metrics.max_winning_streak = max(
                self.metrics.max_winning_streak,
                self.metrics.current_streak
            )
        else:
            if self.metrics.current_streak <= 0:
                self.metrics.current_streak -= 1
            else:
                self.metrics.current_streak = -1
            self.metrics.max_losing_streak = max(
                self.metrics.max_losing_streak,
                abs(self.metrics.current_streak)
            )
        
        # Recalculate metrics from recent history
        self._recalculate_metrics()
    
    def _recalculate_metrics(self):
        """Recalculate metrics from trade history"""
        if not self.trade_history:
            return
        
        # Get recent trades (last 30 days)
        cutoff = datetime.now() - timedelta(days=30)
        recent_trades = [
            t for t in self.trade_history
            if datetime.fromisoformat(t['timestamp']) >= cutoff
        ]
        
        if not recent_trades:
            return
        
        # Calculate win rate
        wins = sum(1 for t in recent_trades if t['was_win'])
        self.metrics.win_rate = wins / len(recent_trades) if recent_trades else 0.5
        
        # Calculate average win/loss
        winning_trades = [t['profit_loss'] for t in recent_trades if t['was_win']]
        losing_trades = [t['profit_loss'] for t in recent_trades if not t['was_win']]
        
        self.metrics.avg_win = statistics.mean(winning_trades) if winning_trades else 0.0
        self.metrics.avg_loss = abs(statistics.mean(losing_trades)) if losing_trades else 0.0
        
        # Calculate profit factor
        total_wins = sum(winning_trades) if winning_trades else 0.0
        total_losses = abs(sum(losing_trades)) if losing_trades else 1.0
        self.metrics.profit_factor = total_wins / total_losses if total_losses > 0 else 1.0
        
        # Calculate returns
        returns = [t['return_pct'] for t in recent_trades]
        self.metrics.monthly_return = sum(returns)
        
        # Calculate Sharpe ratio (simplified)
        if len(returns) > 1:
            mean_return = statistics.mean(returns)
            std_return = statistics.stdev(returns)
            self.metrics.sharpe_ratio = (mean_return / std_return) if std_return > 0 else 0.0
        
        # Update confidence score
        self.metrics.confidence_score = self._calculate_confidence_score()
    
    def _calculate_confidence_score(self) -> float:
        """Calculate confidence score based on multiple factors"""
        score = 0.5  # Start neutral
        
        # Win rate contribution
        score += (self.metrics.win_rate - 0.5) * 0.5
        
        # Profit factor contribution
        score += (min(self.metrics.profit_factor, 3.0) - 1.0) * 0.1
        
        # Sharpe contribution
        score += min(self.metrics.sharpe_ratio, 2.0) * 0.1
        
        # Streak penalty/bonus
        if self.metrics.current_streak < 0:
            score -= abs(self.metrics.current_streak) * 0.02
        
        return max(0.0, min(1.0, score))
    
    def get_performance_report(self) -> str:
        """Generate performance report"""
        lines = [
            "\n" + "=" * 70,
            "PERFORMANCE-BASED RISK SCALING REPORT",
            "=" * 70,
            f"Performance Level: {self._classify_performance_level(self.metrics).value.upper()}",
            "",
            "📊 PERFORMANCE METRICS",
            "-" * 70,
            f"  Monthly Return:       {self.metrics.monthly_return:>12.2%}",
            f"  Sharpe Ratio:         {self.metrics.sharpe_ratio:>12.2f}",
            f"  Win Rate:             {self.metrics.win_rate:>12.1%}",
            f"  Profit Factor:        {self.metrics.profit_factor:>12.2f}",
            f"  Avg Win:              ${self.metrics.avg_win:>12.2f}",
            f"  Avg Loss:             ${self.metrics.avg_loss:>12.2f}",
            "",
            "🔥 STREAKS",
            "-" * 70,
            f"  Current Streak:       {self.metrics.current_streak:>12}",
            f"  Max Win Streak:       {self.metrics.max_winning_streak:>12}",
            f"  Max Loss Streak:      {self.metrics.max_losing_streak:>12}",
            "",
            "📉 DRAWDOWN",
            "-" * 70,
            f"  Current DD:           {self.metrics.current_drawdown_pct:>12.2f}%",
            f"  Max DD:               {self.metrics.max_drawdown_pct:>12.2f}%",
            "",
            "🎯 CONFIDENCE",
            "-" * 70,
            f"  Confidence Score:     {self.metrics.confidence_score:>12.2f}",
            "",
            "=" * 70 + "\n"
        ]
        return "\n".join(lines)


def create_performance_scaling(config: Optional[ScalingConfig] = None) -> PerformanceBasedRiskScaling:
    """
    Factory function to create performance-based scaling.
    
    Args:
        config: Optional configuration
        
    Returns:
        PerformanceBasedRiskScaling instance
    """
    return PerformanceBasedRiskScaling(config)


if __name__ == "__main__":
    # Test/demonstration
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s - %(message)s'
    )
    
    scaling = create_performance_scaling()
    
    # Test with excellent performance
    print("\n" + "="*70)
    print("Testing EXCELLENT performance")
    print("="*70)
    
    metrics = PerformanceMetrics(
        monthly_return=0.18,
        sharpe_ratio=2.2,
        win_rate=0.68,
        profit_factor=2.8,
        current_streak=5,
        current_drawdown_pct=0.0,
        confidence_score=0.85
    )
    
    scaling.update_metrics(metrics)
    result = scaling.calculate_scale_factor(1000.0)
    print(result.get_summary())
    print(scaling.get_performance_report())
    
    # Test with poor performance
    print("\n" + "="*70)
    print("Testing POOR performance")
    print("="*70)
    
    metrics = PerformanceMetrics(
        monthly_return=-0.08,
        sharpe_ratio=0.3,
        win_rate=0.38,
        profit_factor=0.7,
        current_streak=-4,
        current_drawdown_pct=12.0,
        confidence_score=0.25
    )
    
    scaling.update_metrics(metrics)
    result = scaling.calculate_scale_factor(1000.0)
    print(result.get_summary())
    print(scaling.get_performance_report())
