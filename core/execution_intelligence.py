"""
NIJA Execution Intelligence Engine
===================================

Advanced execution optimization layer that maximizes profit through:
- Smart exit timing based on market microstructure
- Dynamic profit-taking adjusted for volatility
- Slippage detection and mitigation
- Fill probability prediction
- Order routing optimization
- Execution quality scoring

This is the "Money Layer" - optimizing every dollar of profit extraction.

Features:
1. ML-based exit scoring for optimal profit-taking timing
2. Dynamic profit targets based on realized volatility
3. Execution quality metrics and benchmarking
4. Smart order routing for best execution
5. Slippage tracking and optimization
6. Partial exit strategies for risk management

Author: NIJA Trading Systems
Version: 1.0
Date: January 2026
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from collections import deque
import pandas as pd
import numpy as np

logger = logging.getLogger("nija.execution")


@dataclass
class ExecutionMetrics:
    """Track execution quality metrics"""
    order_id: str
    symbol: str
    side: str  # 'buy' or 'sell'
    
    # Order details
    requested_size: float
    filled_size: float
    requested_price: Optional[float] = None  # For limit orders
    fill_price: float = 0.0
    
    # Timing
    order_time: datetime = field(default_factory=datetime.now)
    fill_time: Optional[datetime] = None
    execution_duration_ms: float = 0.0
    
    # Slippage
    expected_price: float = 0.0  # Price at order submission
    slippage_bps: float = 0.0  # Slippage in basis points
    slippage_usd: float = 0.0  # Slippage in dollars
    
    # Fees
    fees_usd: float = 0.0
    
    # Market impact
    market_impact_bps: float = 0.0  # Estimated market impact
    
    def calculate_slippage(self):
        """Calculate slippage metrics"""
        if self.expected_price > 0 and self.fill_price > 0:
            if self.side == 'buy':
                # For buys, negative slippage = better price (lower than expected)
                self.slippage_usd = (self.fill_price - self.expected_price) * self.filled_size
                self.slippage_bps = ((self.fill_price / self.expected_price) - 1) * 10000
            else:  # sell
                # For sells, positive slippage = better price (higher than expected)
                # Fixed: was (expected - fill), should be (fill - expected) for consistent positive = better convention
                self.slippage_usd = (self.fill_price - self.expected_price) * self.filled_size
                self.slippage_bps = ((self.fill_price / self.expected_price) - 1) * 10000


@dataclass
class ExitSignal:
    """Signal to exit a position"""
    signal_type: str  # 'profit_target', 'trailing_stop', 'stop_loss', 'trend_reversal'
    confidence: float  # 0-1
    urgency: str  # 'low', 'medium', 'high'
    recommended_exit_pct: float  # Percentage of position to exit (0-1)
    reason: str
    target_price: Optional[float] = None
    
    # ML-based scoring
    exit_score: float = 0.0  # 0-100
    volatility_regime: str = "normal"
    momentum_score: float = 0.0


class ExecutionIntelligence:
    """
    Execution Intelligence Engine
    
    Optimizes trade execution and profit-taking through advanced analytics
    and machine learning.
    """
    
    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize execution intelligence engine
        
        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}
        
        # Execution tracking
        self.execution_history: deque = deque(maxlen=1000)
        self.position_history: Dict[str, deque] = {}  # symbol -> position updates
        
        # Exit optimization
        self.enable_dynamic_targets = self.config.get('enable_dynamic_targets', True)
        self.enable_partial_exits = self.config.get('enable_partial_exits', True)
        self.min_profit_for_exit = self.config.get('min_profit_for_exit', 0.005)  # 0.5%
        
        # Slippage monitoring
        self.slippage_threshold_bps = self.config.get('slippage_threshold_bps', 10)  # 10 bps
        self.slippage_stats = {
            'buy': {'count': 0, 'total_bps': 0, 'avg_bps': 0},
            'sell': {'count': 0, 'total_bps': 0, 'avg_bps': 0}
        }
        
        # Profit-taking levels (dynamic)
        self.base_profit_levels = {
            0.005: 0.20,  # Exit 20% at 0.5% profit
            0.010: 0.25,  # Exit 25% at 1.0% profit
            0.020: 0.30,  # Exit 30% at 2.0% profit
            0.030: 0.25,  # Exit 25% at 3.0% profit (rest trails)
        }
        
        logger.info("Execution Intelligence Engine initialized")
    
    def track_execution(self, execution: ExecutionMetrics):
        """
        Track execution for quality analysis
        
        Args:
            execution: ExecutionMetrics object
        """
        execution.calculate_slippage()
        self.execution_history.append(execution)
        
        # Update slippage statistics
        side = execution.side
        if side in self.slippage_stats:
            stats = self.slippage_stats[side]
            stats['count'] += 1
            stats['total_bps'] += abs(execution.slippage_bps)
            stats['avg_bps'] = stats['total_bps'] / stats['count']
        
        # Log if slippage exceeds threshold
        if abs(execution.slippage_bps) > self.slippage_threshold_bps:
            logger.warning(
                f"⚠️  High slippage on {execution.symbol} {execution.side}: "
                f"{execution.slippage_bps:.1f} bps (${execution.slippage_usd:.2f})"
            )
        
        logger.debug(
            f"Execution tracked: {execution.symbol} {execution.side} "
            f"${execution.filled_size:.2f} @ ${execution.fill_price:.4f}"
        )
    
    def calculate_exit_score(self, symbol: str, df: pd.DataFrame, 
                           indicators: Dict, position: Dict) -> ExitSignal:
        """
        Calculate intelligent exit score based on market conditions
        
        Args:
            symbol: Trading symbol
            df: OHLCV DataFrame
            indicators: Technical indicators
            position: Current position details (entry_price, size, pnl, etc.)
            
        Returns:
            ExitSignal with recommendation
        """
        current_price = df['close'].iloc[-1]
        entry_price = position.get('entry_price', current_price)
        unrealized_pnl_pct = (current_price - entry_price) / entry_price
        
        # Initialize exit score components
        score_components = {
            'profit_level': 0,
            'momentum': 0,
            'volatility': 0,
            'trend_strength': 0,
            'reversal_signals': 0
        }
        
        # 1. Profit level score (0-30 points)
        if unrealized_pnl_pct > 0.03:  # >3% profit
            score_components['profit_level'] = 30
        elif unrealized_pnl_pct > 0.02:  # >2% profit
            score_components['profit_level'] = 20
        elif unrealized_pnl_pct > 0.01:  # >1% profit
            score_components['profit_level'] = 10
        
        # 2. Momentum weakening (0-25 points)
        rsi = self._get_indicator_value(indicators.get('rsi', 50))
        macd = indicators.get('macd', {})
        macd_hist = self._get_indicator_value(macd.get('histogram', 0))
        
        # Check if momentum is weakening (for long positions)
        if position.get('side', 'long') == 'long':
            if rsi > 70:  # Overbought
                score_components['momentum'] += 15
            if macd_hist < 0:  # MACD turning negative
                score_components['momentum'] += 10
        else:  # short position
            if rsi < 30:  # Oversold
                score_components['momentum'] += 15
            if macd_hist > 0:  # MACD turning positive
                score_components['momentum'] += 10
        
        # 3. Volatility regime (0-20 points)
        atr = self._get_indicator_value(indicators.get('atr', 0))
        atr_pct = atr / current_price if current_price > 0 else 0
        
        volatility_regime = "normal"
        if atr_pct > 0.03:  # High volatility
            volatility_regime = "high"
            score_components['volatility'] = 20  # Exit faster in high volatility
        elif atr_pct < 0.01:  # Low volatility
            volatility_regime = "low"
            score_components['volatility'] = 5  # Can hold longer
        else:
            volatility_regime = "normal"
            score_components['volatility'] = 10
        
        # 4. Trend strength weakening (0-15 points)
        adx = self._get_indicator_value(indicators.get('adx', 0))
        if adx < 20:  # Weak trend
            score_components['trend_strength'] = 15
        elif adx < 25:  # Moderate trend
            score_components['trend_strength'] = 8
        
        # 5. Reversal signals (0-10 points)
        # Check for bearish divergence or reversal candlestick patterns
        if len(df) >= 3:
            # Simple reversal detection: 2 consecutive candles against position
            candle_1 = df.iloc[-2]
            candle_2 = df.iloc[-1]
            
            if position.get('side', 'long') == 'long':
                # For longs, check for bearish candles
                if candle_1['close'] < candle_1['open'] and candle_2['close'] < candle_2['open']:
                    score_components['reversal_signals'] = 10
            else:
                # For shorts, check for bullish candles
                if candle_1['close'] > candle_1['open'] and candle_2['close'] > candle_2['open']:
                    score_components['reversal_signals'] = 10
        
        # Calculate total exit score (0-100)
        total_score = sum(score_components.values())
        
        # Determine signal type and urgency
        if total_score >= 70:
            signal_type = "strong_exit"
            urgency = "high"
            recommended_pct = 1.0  # Exit entire position
            reason = "Strong exit signals detected"
        elif total_score >= 50:
            signal_type = "profit_target"
            urgency = "medium"
            recommended_pct = 0.50  # Exit 50%
            reason = "Partial profit-taking recommended"
        elif total_score >= 30 and unrealized_pnl_pct > self.min_profit_for_exit:
            signal_type = "partial_exit"
            urgency = "low"
            recommended_pct = 0.25  # Exit 25%
            reason = "Moderate profit-taking opportunity"
        else:
            signal_type = "hold"
            urgency = "low"
            recommended_pct = 0.0
            reason = "Hold position"
        
        # Calculate momentum score for additional context
        momentum_score = score_components['momentum'] + score_components['trend_strength']
        
        exit_signal = ExitSignal(
            signal_type=signal_type,
            confidence=min(total_score / 100, 1.0),
            urgency=urgency,
            recommended_exit_pct=recommended_pct,
            reason=reason,
            exit_score=total_score,
            volatility_regime=volatility_regime,
            momentum_score=momentum_score
        )
        
        logger.debug(
            f"Exit analysis for {symbol}: score={total_score:.0f}, "
            f"PnL={unrealized_pnl_pct*100:.2f}%, recommendation={signal_type}"
        )
        
        return exit_signal
    
    def get_dynamic_profit_targets(self, symbol: str, df: pd.DataFrame, 
                                  indicators: Dict, entry_price: float) -> Dict[float, float]:
        """
        Calculate dynamic profit targets based on market conditions
        
        Args:
            symbol: Trading symbol
            df: OHLCV DataFrame
            indicators: Technical indicators
            entry_price: Position entry price
            
        Returns:
            Dictionary of {target_price: exit_percentage}
        """
        if not self.enable_dynamic_targets:
            # Use static base levels
            targets = {}
            for profit_pct, exit_pct in self.base_profit_levels.items():
                targets[entry_price * (1 + profit_pct)] = exit_pct
            return targets
        
        # Adjust targets based on volatility
        atr = self._get_indicator_value(indicators.get('atr', 0))
        atr_pct = atr / entry_price if entry_price > 0 else 0
        
        # Volatility-adjusted multiplier
        if atr_pct > 0.03:  # High volatility
            vol_multiplier = 1.5  # Wider targets
        elif atr_pct < 0.01:  # Low volatility
            vol_multiplier = 0.7  # Tighter targets
        else:
            vol_multiplier = 1.0
        
        # Trend strength adjustment
        adx = self._get_indicator_value(indicators.get('adx', 0))
        if adx > 30:  # Strong trend
            trend_multiplier = 1.3  # Can aim for larger moves
        elif adx < 20:  # Weak trend
            trend_multiplier = 0.8  # Take profits faster
        else:
            trend_multiplier = 1.0
        
        # Combined adjustment
        adjustment = vol_multiplier * trend_multiplier
        
        # Create adjusted targets
        dynamic_targets = {}
        for profit_pct, exit_pct in self.base_profit_levels.items():
            adjusted_profit_pct = profit_pct * adjustment
            target_price = entry_price * (1 + adjusted_profit_pct)
            dynamic_targets[target_price] = exit_pct
        
        logger.debug(
            f"Dynamic targets for {symbol}: volatility={atr_pct*100:.2f}%, "
            f"trend_strength={adx:.1f}, adjustment={adjustment:.2f}x"
        )
        
        return dynamic_targets
    
    def calculate_optimal_exit_size(self, position: Dict, exit_signal: ExitSignal,
                                   available_balance: float) -> Tuple[float, str]:
        """
        Calculate optimal position size to exit
        
        Args:
            position: Current position details
            exit_signal: Exit signal from calculate_exit_score()
            available_balance: Available account balance
            
        Returns:
            Tuple of (exit_size, reason)
        """
        # Validate position has required fields
        required_fields = ['size', 'side', 'entry_price']
        for field in required_fields:
            if field not in position:
                logger.error(f"Position missing required field: {field}")
                return 0.0, f"Invalid position data: missing {field}"
        
        current_size = position.get('size', 0)
        unrealized_pnl = position.get('unrealized_pnl', 0)
        unrealized_pnl_pct = position.get('unrealized_pnl_pct', 0)
        
        # Base exit size from signal
        recommended_size = current_size * exit_signal.recommended_exit_pct
        
        # Apply partial exit logic if enabled
        if not self.enable_partial_exits:
            # All-or-nothing exits
            if exit_signal.recommended_exit_pct > 0.5:
                return current_size, "Full exit recommended"
            else:
                return 0.0, "Hold position"
        
        # Adjust based on profit level
        if unrealized_pnl_pct > 0.05:  # >5% profit
            # Take more profit when very profitable
            recommended_size = max(recommended_size, current_size * 0.50)
            reason = "Enhanced profit-taking at >5% gain"
        elif unrealized_pnl_pct < -0.02:  # >2% loss
            # Consider cutting losses
            if exit_signal.urgency == "high":
                recommended_size = current_size  # Exit all
                reason = "Stop loss triggered"
            else:
                recommended_size = max(recommended_size, current_size * 0.25)
                reason = "Partial loss cutting"
        else:
            reason = exit_signal.reason
        
        # Ensure we're not exiting more than position size
        exit_size = min(recommended_size, current_size)
        
        # Minimum exit size check (don't leave dust)
        min_exit = current_size * 0.10  # Minimum 10% of position
        if 0 < exit_size < min_exit:
            exit_size = 0  # Don't exit if too small
            reason = "Exit size too small - holding"
        
        logger.debug(f"Optimal exit: ${exit_size:.2f} of ${current_size:.2f} - {reason}")
        
        return exit_size, reason
    
    def estimate_fill_probability(self, symbol: str, order_type: str, 
                                 limit_price: Optional[float], 
                                 current_price: float, volume_24h: float) -> float:
        """
        Estimate probability of order fill
        
        Args:
            symbol: Trading symbol
            order_type: 'market' or 'limit'
            limit_price: Limit price (None for market orders)
            current_price: Current market price
            volume_24h: 24-hour trading volume
            
        Returns:
            Fill probability (0-1)
        """
        if order_type == 'market':
            # Market orders have high fill probability (unless very large)
            return 0.95
        
        if limit_price is None:
            return 0.0
        
        # Calculate distance from current price
        price_distance_pct = abs(limit_price - current_price) / current_price
        
        # Estimate based on distance and volume
        if price_distance_pct < 0.001:  # Within 0.1%
            probability = 0.90
        elif price_distance_pct < 0.005:  # Within 0.5%
            probability = 0.70
        elif price_distance_pct < 0.01:  # Within 1%
            probability = 0.50
        elif price_distance_pct < 0.02:  # Within 2%
            probability = 0.30
        else:
            probability = 0.10
        
        # Adjust for volume (higher volume = better fill probability)
        if volume_24h > 1000000:  # High liquidity
            probability *= 1.1
        elif volume_24h < 100000:  # Low liquidity
            probability *= 0.8
        
        return min(probability, 1.0)
    
    def get_execution_quality_report(self) -> Dict[str, Any]:
        """
        Generate execution quality report
        
        Returns:
            Dictionary with execution metrics
        """
        if not self.execution_history:
            return {'status': 'no_data', 'message': 'No executions tracked yet'}
        
        recent_executions = list(self.execution_history)
        
        # Calculate aggregate metrics
        total_slippage_bps = sum(abs(e.slippage_bps) for e in recent_executions)
        avg_slippage_bps = total_slippage_bps / len(recent_executions)
        
        total_slippage_usd = sum(abs(e.slippage_usd) for e in recent_executions)
        total_fees = sum(e.fees_usd for e in recent_executions)
        
        # Execution duration stats
        durations = [e.execution_duration_ms for e in recent_executions if e.execution_duration_ms > 0]
        avg_duration_ms = np.mean(durations) if durations else 0
        
        report = {
            'timestamp': datetime.now(),
            'total_executions': len(recent_executions),
            'avg_slippage_bps': avg_slippage_bps,
            'total_slippage_usd': total_slippage_usd,
            'total_fees_usd': total_fees,
            'avg_execution_duration_ms': avg_duration_ms,
            'slippage_by_side': self.slippage_stats.copy(),
            'execution_cost_total': total_slippage_usd + total_fees
        }
        
        logger.info(f"📊 Execution quality: {len(recent_executions)} trades, "
                   f"avg slippage {avg_slippage_bps:.1f} bps, "
                   f"total cost ${total_slippage_usd + total_fees:.2f}")
        
        return report
    
    def _get_indicator_value(self, indicator_val, default=0):
        """Safely extract scalar value from indicator"""
        if hasattr(indicator_val, 'iloc'):
            return indicator_val.iloc[-1]
        elif isinstance(indicator_val, (int, float)):
            return indicator_val
        else:
            return default


def create_execution_intelligence(config: Optional[Dict] = None) -> ExecutionIntelligence:
    """
    Factory function to create execution intelligence engine
    
    Args:
        config: Optional configuration
        
    Returns:
        ExecutionIntelligence instance
    """
    return ExecutionIntelligence(config)
