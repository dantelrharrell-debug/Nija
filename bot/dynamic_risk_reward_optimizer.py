"""
NIJA Dynamic Risk-Reward Optimizer
===================================

Automatically optimizes stop-loss and profit target levels based on:
1. Market volatility (ATR-based)
2. Support/resistance levels
3. Win rate statistics
4. Market regime
5. Time of day patterns

This ensures optimal risk-reward ratios that adapt to market conditions
for faster growth and better capital preservation.

Author: NIJA Trading Systems
Version: 1.0
Date: January 30, 2026
"""

import logging
import numpy as np
from typing import Dict, Optional, Tuple, List
from dataclasses import dataclass
from enum import Enum
from datetime import datetime

logger = logging.getLogger("nija.risk_reward_optimizer")


class RiskRewardMode(Enum):
    """Risk-reward optimization modes"""
    CONSERVATIVE = "conservative"  # 1:2 R:R, tight stops
    BALANCED = "balanced"  # 1:3 R:R, moderate stops
    AGGRESSIVE = "aggressive"  # 1:4 R:R, wider stops
    OPTIMAL = "optimal"  # Dynamic based on market conditions


@dataclass
class RiskRewardConfig:
    """Configuration for risk-reward optimization"""
    mode: RiskRewardMode = RiskRewardMode.OPTIMAL
    
    # Base risk-reward ratios
    min_risk_reward: float = 2.0  # Minimum 1:2
    target_risk_reward: float = 3.0  # Target 1:3
    max_risk_reward: float = 5.0  # Maximum 1:5
    
    # Stop loss settings (as % of ATR)
    min_stop_loss_atr: float = 1.0  # Minimum 1x ATR
    default_stop_loss_atr: float = 2.0  # Default 2x ATR
    max_stop_loss_atr: float = 4.0  # Maximum 4x ATR
    
    # Profit target settings (as % of ATR)
    min_profit_target_atr: float = 3.0  # Minimum 3x ATR
    default_profit_target_atr: float = 6.0  # Default 6x ATR
    max_profit_target_atr: float = 12.0  # Maximum 12x ATR
    
    # Trailing stop settings
    enable_trailing_stop: bool = True
    trailing_stop_activation: float = 0.5  # Activate after 50% of target
    trailing_stop_distance_pct: float = 0.25  # Trail 25% from peak
    
    # Adaptive settings
    adapt_to_volatility: bool = True
    adapt_to_regime: bool = True
    adapt_to_win_rate: bool = True


class DynamicRiskRewardOptimizer:
    """
    Optimizes stop-loss and profit target placement based on multiple factors
    
    Key Features:
    1. ATR-based dynamic stops (wider in volatile markets)
    2. Win rate optimization (tighter targets if struggling)
    3. Regime adaptation (aggressive in trends, conservative in chop)
    4. Trailing stop management
    5. Support/resistance integration
    """
    
    def __init__(self, config: Optional[RiskRewardConfig] = None):
        """
        Initialize Dynamic Risk-Reward Optimizer
        
        Args:
            config: Risk-reward configuration
        """
        self.config = config or RiskRewardConfig()
        
        # Performance tracking
        self.recent_trades: List[Dict] = []
        self.win_rate = 0.50
        self.avg_win_rr = 3.0  # Average R:R on wins
        self.avg_loss_rr = 1.0  # Average R:R on losses
        
        logger.info("=" * 70)
        logger.info("🎯 Dynamic Risk-Reward Optimizer Initialized")
        logger.info("=" * 70)
        logger.info(f"Mode: {self.config.mode.value}")
        logger.info(f"Target R:R: 1:{self.config.target_risk_reward:.1f}")
        logger.info(f"Stop Loss: {self.config.default_stop_loss_atr:.1f}x ATR")
        logger.info(f"Profit Target: {self.config.default_profit_target_atr:.1f}x ATR")
        logger.info(f"Trailing Stop: {'ENABLED' if self.config.enable_trailing_stop else 'DISABLED'}")
        logger.info("=" * 70)
    
    def calculate_optimal_levels(
        self,
        entry_price: float,
        atr: float,
        direction: str = "long",
        win_rate: Optional[float] = None,
        volatility_regime: str = "normal",
        trend_strength: Optional[float] = None,
        support_level: Optional[float] = None,
        resistance_level: Optional[float] = None
    ) -> Dict:
        """
        Calculate optimal stop-loss and profit target levels
        
        Args:
            entry_price: Entry price
            atr: Average True Range
            direction: Trade direction ("long" or "short")
            win_rate: Recent win rate (0-1)
            volatility_regime: Volatility regime (low/normal/high)
            trend_strength: Trend strength (0-100, e.g., ADX)
            support_level: Support price level
            resistance_level: Resistance price level
        
        Returns:
            Dictionary with stop-loss and profit target levels
        """
        # Use provided win rate or default
        if win_rate is not None:
            self.win_rate = win_rate
        
        # Calculate base stop loss (ATR-based)
        stop_loss_atr_multiplier = self._calculate_stop_loss_multiplier(
            volatility_regime, trend_strength
        )
        
        stop_distance = atr * stop_loss_atr_multiplier
        
        # Calculate base profit target
        profit_target_atr_multiplier = self._calculate_profit_target_multiplier(
            volatility_regime, trend_strength
        )
        
        profit_distance = atr * profit_target_atr_multiplier
        
        # Calculate actual prices
        if direction.lower() == "long":
            stop_loss = entry_price - stop_distance
            profit_target = entry_price + profit_distance
            
            # Adjust for support/resistance
            if support_level and support_level > stop_loss:
                # Move stop below support
                stop_loss = support_level * 0.998  # 0.2% below support
                logger.info(f"✅ Stop adjusted to ${stop_loss:.2f} (below support ${support_level:.2f})")
            
            if resistance_level and resistance_level < profit_target:
                # Move target below resistance
                profit_target = resistance_level * 0.995  # 0.5% below resistance
                logger.info(f"✅ Target adjusted to ${profit_target:.2f} (below resistance ${resistance_level:.2f})")
        
        else:  # short
            stop_loss = entry_price + stop_distance
            profit_target = entry_price - profit_distance
            
            # Adjust for support/resistance
            if resistance_level and resistance_level < stop_loss:
                # Move stop above resistance
                stop_loss = resistance_level * 1.002  # 0.2% above resistance
                logger.info(f"✅ Stop adjusted to ${stop_loss:.2f} (above resistance ${resistance_level:.2f})")
            
            if support_level and support_level > profit_target:
                # Move target above support
                profit_target = support_level * 1.005  # 0.5% above support
                logger.info(f"✅ Target adjusted to ${profit_target:.2f} (above support ${support_level:.2f})")
        
        # Recalculate actual distances after adjustments
        actual_stop_distance = abs(entry_price - stop_loss)
        actual_profit_distance = abs(profit_target - entry_price)
        
        # Calculate risk-reward ratio
        risk_reward = actual_profit_distance / actual_stop_distance if actual_stop_distance > 0 else 0
        
        # Validate and adjust if needed
        if risk_reward < self.config.min_risk_reward:
            logger.warning(f"⚠️  R:R {risk_reward:.2f} below minimum {self.config.min_risk_reward:.2f}")
            # Extend profit target to meet minimum R:R
            required_profit_distance = actual_stop_distance * self.config.min_risk_reward
            if direction.lower() == "long":
                profit_target = entry_price + required_profit_distance
            else:
                profit_target = entry_price - required_profit_distance
            risk_reward = self.config.min_risk_reward
            logger.info(f"✅ Adjusted profit target to ${profit_target:.2f} for R:R={risk_reward:.2f}")
        
        # Calculate trailing stop levels
        trailing_levels = None
        if self.config.enable_trailing_stop:
            trailing_levels = self._calculate_trailing_stop_levels(
                entry_price, stop_loss, profit_target, direction
            )
        
        result = {
            'entry_price': entry_price,
            'stop_loss': stop_loss,
            'profit_target': profit_target,
            'stop_distance': actual_stop_distance,
            'profit_distance': actual_profit_distance,
            'risk_reward_ratio': risk_reward,
            'stop_loss_atr_multiplier': stop_loss_atr_multiplier,
            'profit_target_atr_multiplier': profit_target_atr_multiplier,
            'atr': atr,
            'direction': direction,
            'trailing_stop_levels': trailing_levels,
            'volatility_regime': volatility_regime,
        }
        
        logger.info(f"🎯 Optimal Levels Calculated:")
        logger.info(f"   Entry: ${entry_price:.2f}")
        logger.info(f"   Stop Loss: ${stop_loss:.2f} ({actual_stop_distance:.2f} | {stop_loss_atr_multiplier:.1f}x ATR)")
        logger.info(f"   Profit Target: ${profit_target:.2f} ({actual_profit_distance:.2f} | {profit_target_atr_multiplier:.1f}x ATR)")
        logger.info(f"   Risk:Reward = 1:{risk_reward:.2f}")
        
        return result
    
    def _calculate_stop_loss_multiplier(
        self, volatility_regime: str, trend_strength: Optional[float]
    ) -> float:
        """
        Calculate stop loss ATR multiplier based on conditions
        
        Logic:
        - High volatility → Wider stops (avoid getting stopped out)
        - Low volatility → Tighter stops (reduce risk)
        - Strong trend → Wider stops (let winners run)
        - Weak trend → Tighter stops (reduce whipsaw risk)
        """
        base_multiplier = self.config.default_stop_loss_atr
        
        # Adjust for volatility
        if self.config.adapt_to_volatility:
            if volatility_regime == "high":
                base_multiplier *= 1.5  # 50% wider in high vol
            elif volatility_regime == "low":
                base_multiplier *= 0.75  # 25% tighter in low vol
        
        # Adjust for trend strength
        if self.config.adapt_to_regime and trend_strength is not None:
            if trend_strength >= 40:  # Strong trend
                base_multiplier *= 1.2  # 20% wider in strong trends
            elif trend_strength < 25:  # Weak trend
                base_multiplier *= 0.8  # 20% tighter in weak trends
        
        # Ensure within bounds
        base_multiplier = max(
            min(base_multiplier, self.config.max_stop_loss_atr),
            self.config.min_stop_loss_atr
        )
        
        return base_multiplier
    
    def _calculate_profit_target_multiplier(
        self, volatility_regime: str, trend_strength: Optional[float]
    ) -> float:
        """
        Calculate profit target ATR multiplier based on conditions
        
        Logic:
        - High volatility → Wider targets (capture big moves)
        - Strong trend → Wider targets (ride the trend)
        - Low win rate → Wider targets (need better R:R)
        """
        base_multiplier = self.config.default_profit_target_atr
        
        # Adjust for volatility
        if self.config.adapt_to_volatility:
            if volatility_regime == "high":
                base_multiplier *= 1.5  # 50% wider in high vol
            elif volatility_regime == "low":
                base_multiplier *= 0.85  # 15% tighter in low vol
        
        # Adjust for trend strength
        if self.config.adapt_to_regime and trend_strength is not None:
            if trend_strength >= 40:  # Strong trend
                base_multiplier *= 1.3  # 30% wider in strong trends (let winners run)
            elif trend_strength < 25:  # Weak trend
                base_multiplier *= 0.9  # 10% tighter in weak trends
        
        # Adjust for win rate
        if self.config.adapt_to_win_rate:
            if self.win_rate < 0.50:
                # Low win rate → Need better R:R
                base_multiplier *= 1.2
            elif self.win_rate > 0.65:
                # High win rate → Can use tighter targets
                base_multiplier *= 0.9
        
        # Ensure within bounds
        base_multiplier = max(
            min(base_multiplier, self.config.max_profit_target_atr),
            self.config.min_profit_target_atr
        )
        
        return base_multiplier
    
    def _calculate_trailing_stop_levels(
        self, entry_price: float, stop_loss: float,
        profit_target: float, direction: str
    ) -> Dict:
        """Calculate trailing stop activation and distance levels"""
        profit_distance = abs(profit_target - entry_price)
        activation_distance = profit_distance * self.config.trailing_stop_activation
        
        if direction.lower() == "long":
            activation_price = entry_price + activation_distance
            trail_distance_pct = self.config.trailing_stop_distance_pct
        else:
            activation_price = entry_price - activation_distance
            trail_distance_pct = self.config.trailing_stop_distance_pct
        
        return {
            'activation_price': activation_price,
            'activation_distance': activation_distance,
            'trail_distance_pct': trail_distance_pct,
            'initial_stop': stop_loss,
        }
    
    def calculate_breakeven_stop(
        self, entry_price: float, current_price: float,
        initial_stop: float, direction: str = "long"
    ) -> Tuple[bool, float]:
        """
        Calculate if position should move to breakeven
        
        Args:
            entry_price: Entry price
            current_price: Current market price
            initial_stop: Initial stop loss
            direction: Trade direction
        
        Returns:
            Tuple of (should_move_to_breakeven, new_stop_price)
        """
        profit_pct = (current_price - entry_price) / entry_price * 100
        
        # Move to breakeven after 1% profit (or 1R)
        breakeven_threshold = 1.0  # 1%
        
        if direction.lower() == "long":
            if profit_pct >= breakeven_threshold:
                # Move stop to breakeven (entry + small buffer)
                new_stop = entry_price * 1.001  # 0.1% above entry
                return (True, new_stop)
        else:  # short
            if profit_pct <= -breakeven_threshold:
                # Move stop to breakeven (entry - small buffer)
                new_stop = entry_price * 0.999  # 0.1% below entry
                return (True, new_stop)
        
        return (False, initial_stop)
    
    def update_trailing_stop(
        self, entry_price: float, current_price: float,
        current_stop: float, peak_price: float,
        trailing_config: Dict, direction: str = "long"
    ) -> Tuple[bool, float]:
        """
        Update trailing stop based on current price movement
        
        Args:
            entry_price: Entry price
            current_price: Current market price
            current_stop: Current stop loss price
            peak_price: Peak price reached (high for long, low for short)
            trailing_config: Trailing stop configuration from calculate_optimal_levels
            direction: Trade direction
        
        Returns:
            Tuple of (stop_updated, new_stop_price)
        """
        if not trailing_config:
            return (False, current_stop)
        
        activation_price = trailing_config['activation_price']
        trail_distance_pct = trailing_config['trail_distance_pct']
        
        if direction.lower() == "long":
            # Check if trailing is activated
            if peak_price < activation_price:
                return (False, current_stop)
            
            # Calculate trailing stop (% below peak)
            new_stop = peak_price * (1 - trail_distance_pct)
            
            # Only update if new stop is higher than current
            if new_stop > current_stop:
                logger.info(f"📈 Trailing stop updated: ${current_stop:.2f} → ${new_stop:.2f}")
                return (True, new_stop)
        
        else:  # short
            # Check if trailing is activated
            if peak_price > activation_price:
                return (False, current_stop)
            
            # Calculate trailing stop (% above peak)
            new_stop = peak_price * (1 + trail_distance_pct)
            
            # Only update if new stop is lower than current
            if new_stop < current_stop:
                logger.info(f"📉 Trailing stop updated: ${current_stop:.2f} → ${new_stop:.2f}")
                return (True, new_stop)
        
        return (False, current_stop)
    
    def record_trade_result(
        self, entry_price: float, exit_price: float,
        stop_loss: float, profit_target: float, direction: str
    ):
        """
        Record trade result for performance tracking
        
        Args:
            entry_price: Entry price
            exit_price: Exit price
            stop_loss: Stop loss price
            profit_target: Profit target price
            direction: Trade direction
        """
        # Calculate R achieved
        stop_distance = abs(entry_price - stop_loss)
        
        if direction.lower() == "long":
            pnl = exit_price - entry_price
        else:
            pnl = entry_price - exit_price
        
        r_achieved = pnl / stop_distance if stop_distance > 0 else 0
        is_win = pnl > 0
        
        # Store trade
        trade_record = {
            'timestamp': datetime.now().isoformat(),
            'entry_price': entry_price,
            'exit_price': exit_price,
            'stop_loss': stop_loss,
            'profit_target': profit_target,
            'direction': direction,
            'r_achieved': r_achieved,
            'is_win': is_win,
        }
        
        self.recent_trades.append(trade_record)
        
        # Keep only last 100 trades
        if len(self.recent_trades) > 100:
            self.recent_trades = self.recent_trades[-100:]
        
        # Update statistics
        self._update_statistics()
        
        logger.info(f"📊 Trade Recorded: {'WIN ✅' if is_win else 'LOSS ❌'} | R={r_achieved:.2f}")
    
    def _update_statistics(self):
        """Update win rate and R statistics"""
        if not self.recent_trades:
            return
        
        wins = [t for t in self.recent_trades if t['is_win']]
        losses = [t for t in self.recent_trades if not t['is_win']]
        
        self.win_rate = len(wins) / len(self.recent_trades)
        
        if wins:
            self.avg_win_rr = np.mean([t['r_achieved'] for t in wins])
        
        if losses:
            self.avg_loss_rr = abs(np.mean([t['r_achieved'] for t in losses]))
        
        logger.debug(
            f"📊 Stats Updated: Win Rate={self.win_rate*100:.1f}%, "
            f"Avg Win={self.avg_win_rr:.2f}R, Avg Loss={self.avg_loss_rr:.2f}R"
        )
    
    def get_performance_summary(self) -> Dict:
        """Get performance summary"""
        return {
            'total_trades': len(self.recent_trades),
            'win_rate': self.win_rate,
            'avg_win_rr': self.avg_win_rr,
            'avg_loss_rr': self.avg_loss_rr,
            'expectancy': self.win_rate * self.avg_win_rr - (1 - self.win_rate) * self.avg_loss_rr,
        }


def create_risk_reward_optimizer(
    mode: str = "optimal",
    target_risk_reward: float = 3.0,
    enable_trailing: bool = True
) -> DynamicRiskRewardOptimizer:
    """
    Factory function to create DynamicRiskRewardOptimizer
    
    Args:
        mode: Optimization mode (conservative/balanced/aggressive/optimal)
        target_risk_reward: Target risk-reward ratio
        enable_trailing: Enable trailing stops
    
    Returns:
        DynamicRiskRewardOptimizer instance
    """
    mode_enum = RiskRewardMode(mode.lower())
    
    config = RiskRewardConfig(
        mode=mode_enum,
        target_risk_reward=target_risk_reward,
        enable_trailing_stop=enable_trailing
    )
    
    return DynamicRiskRewardOptimizer(config)


if __name__ == "__main__":
    # Test/demonstration
    import logging
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s - %(message)s'
    )
    
    # Create optimizer
    optimizer = create_risk_reward_optimizer(
        mode="optimal",
        target_risk_reward=3.0,
        enable_trailing=True
    )
    
    print("\n" + "=" * 70)
    print("DYNAMIC RISK-REWARD OPTIMIZATION EXAMPLE")
    print("=" * 70)
    
    # Calculate levels for a long trade
    result = optimizer.calculate_optimal_levels(
        entry_price=100.0,
        atr=2.5,
        direction="long",
        win_rate=0.65,
        volatility_regime="normal",
        trend_strength=35,  # Moderate trend
        support_level=97.0,
        resistance_level=110.0
    )
    
    print(f"\n📊 Trade Setup:")
    print(f"   Entry: ${result['entry_price']:.2f}")
    print(f"   Stop Loss: ${result['stop_loss']:.2f}")
    print(f"   Profit Target: ${result['profit_target']:.2f}")
    print(f"   Risk:Reward = 1:{result['risk_reward_ratio']:.2f}")
    
    # Simulate trade progression
    print(f"\n📈 Simulating trade progression...")
    
    # Price moves up to $105 (50% of target)
    should_trail, new_stop = optimizer.calculate_breakeven_stop(
        entry_price=100.0,
        current_price=105.0,
        initial_stop=result['stop_loss'],
        direction="long"
    )
    
    if should_trail:
        print(f"   ✅ Moved to breakeven: Stop=${new_stop:.2f}")
    
    # Price reaches $108 (activates trailing stop)
    updated, trailing_stop = optimizer.update_trailing_stop(
        entry_price=100.0,
        current_price=108.0,
        current_stop=new_stop if should_trail else result['stop_loss'],
        peak_price=108.0,
        trailing_config=result['trailing_stop_levels'],
        direction="long"
    )
    
    if updated:
        print(f"   ✅ Trailing stop activated: ${trailing_stop:.2f}")
    
    # Record trade result (assume exit at $107)
    optimizer.record_trade_result(
        entry_price=100.0,
        exit_price=107.0,
        stop_loss=result['stop_loss'],
        profit_target=result['profit_target'],
        direction="long"
    )
    
    # Show performance summary
    summary = optimizer.get_performance_summary()
    print(f"\n📊 Performance Summary:")
    print(f"   Total Trades: {summary['total_trades']}")
    print(f"   Win Rate: {summary['win_rate']*100:.1f}%")
    print(f"   Expectancy: {summary['expectancy']:.2f}R")
