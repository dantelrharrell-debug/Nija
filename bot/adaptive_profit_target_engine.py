"""
NIJA Adaptive Profit Target Engine
===================================

GOD-TIER ENHANCEMENT #1: Dynamic exit calculations based on:
1. Trend strength (stronger trends = wider profit targets)
2. Volatility regime (higher volatility = wider targets)
3. Momentum indicators (divergence = tighter targets)
4. Time-of-day liquidity patterns

This module dynamically expands or contracts profit targets in real-time
based on market conditions, maximizing profit extraction while protecting gains.

Author: NIJA Trading Systems
Version: 1.0 - God-Tier Edition
Date: January 2026
"""

import pandas as pd
import numpy as np
from typing import Dict, Tuple, List, Optional
from enum import Enum
from datetime import datetime
import logging

logger = logging.getLogger("nija.adaptive_profit")


class TrendStrength(Enum):
    """Trend strength classifications"""
    WEAK = "weak"           # ADX < 25
    MODERATE = "moderate"   # ADX 25-35
    STRONG = "strong"       # ADX 35-50
    EXTREME = "extreme"     # ADX > 50


class AdaptiveProfitTargetEngine:
    """
    Dynamically adjust profit targets based on market conditions
    
    Key Features:
    - Expands targets in strong trends (capture bigger moves)
    - Contracts targets in weak trends (lock profits faster)
    - Adjusts for volatility (wider targets in volatile markets)
    - Detects momentum divergence (tighten targets when momentum fades)
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize Adaptive Profit Target Engine
        
        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}
        
        # Base profit target levels (percentage moves from entry)
        self.base_targets = {
            'tp1': 0.005,  # 0.5%
            'tp2': 0.010,  # 1.0%
            'tp3': 0.020,  # 2.0%
            'tp4': 0.030,  # 3.0%
            'tp5': 0.050,  # 5.0% (extreme trends only)
        }
        
        # Exit percentage at each target level
        self.exit_percentages = {
            'tp1': 0.10,  # Exit 10% at TP1
            'tp2': 0.15,  # Exit 15% at TP2
            'tp3': 0.25,  # Exit 25% at TP3
            'tp4': 0.30,  # Exit 30% at TP4
            'tp5': 0.20,  # Exit 20% at TP5 (rest to trailing stop)
        }
        
        # Trend strength multipliers for profit targets
        self.trend_multipliers = {
            TrendStrength.WEAK: 0.7,      # Contract by 30% in weak trends
            TrendStrength.MODERATE: 1.0,  # Normal targets
            TrendStrength.STRONG: 1.5,    # Expand by 50% in strong trends
            TrendStrength.EXTREME: 2.0,   # Expand by 100% in extreme trends
        }
        
        # Volatility regime multipliers
        self.volatility_multipliers = {
            'extreme_high': 1.8,  # Wider targets in high volatility
            'high': 1.4,
            'normal': 1.0,
            'low': 0.8,
            'extreme_low': 0.6,   # Tighter targets in low volatility
        }
        
        # Minimum and maximum target multipliers (safety bounds)
        self.min_multiplier = 0.5   # Never contract below 50%
        self.max_multiplier = 2.5   # Never expand beyond 250%
        
        # Momentum divergence detection thresholds
        self.divergence_threshold = 0.15  # 15% divergence triggers tightening
        
        logger.info("✅ Adaptive Profit Target Engine initialized")
        logger.info(f"   Base targets: {list(self.base_targets.values())}")
        logger.info(f"   Trend multiplier range: {min(self.trend_multipliers.values()):.1f}x - {max(self.trend_multipliers.values()):.1f}x")
    
    def calculate_adaptive_targets(
        self,
        entry_price: float,
        side: str,
        df: pd.DataFrame,
        indicators: Dict,
        current_regime: str = 'normal',
        atr: Optional[float] = None
    ) -> Dict:
        """
        Calculate adaptive profit targets based on current market conditions
        
        Args:
            entry_price: Position entry price
            side: 'long' or 'short' (case-insensitive)
            df: Price DataFrame with OHLCV data
            indicators: Dictionary of calculated indicators
            current_regime: Current volatility regime
            atr: Optional ATR value for stop loss calculation
            
        Returns:
            Dictionary with adaptive profit targets and metadata
        """
        # Normalize side parameter to lowercase
        side = side.lower()
        # 1. Assess trend strength
        trend_strength, trend_metrics = self._assess_trend_strength(indicators)
        
        # 2. Detect momentum divergence
        has_divergence, divergence_score = self._detect_momentum_divergence(df, indicators)
        
        # 3. Calculate combined multiplier
        trend_mult = self.trend_multipliers[trend_strength]
        vol_mult = self.volatility_multipliers.get(current_regime, 1.0)
        
        # Reduce multiplier if divergence detected
        divergence_penalty = 1.0 - (divergence_score * 0.5) if has_divergence else 1.0
        
        # Combined multiplier with safety bounds
        combined_multiplier = trend_mult * vol_mult * divergence_penalty
        combined_multiplier = max(self.min_multiplier, min(self.max_multiplier, combined_multiplier))
        
        # 4. Generate adaptive targets
        adaptive_targets = {}
        for level, base_pct in self.base_targets.items():
            # Apply multiplier to base percentage
            adjusted_pct = base_pct * combined_multiplier
            
            # Calculate actual price
            if side in ['long', 'buy']:
                target_price = entry_price * (1 + adjusted_pct)
            else:  # short
                target_price = entry_price * (1 - adjusted_pct)
            
            adaptive_targets[level] = {
                'price': target_price,
                'percentage': adjusted_pct,
                'exit_pct': self.exit_percentages[level],
                'distance_from_entry': abs(target_price - entry_price),
            }
        
        # 5. Calculate trailing stop activation point
        trailing_activation_pct = 0.015 * combined_multiplier  # 1.5% base, scaled
        if side in ['long', 'buy']:
            trailing_activation = entry_price * (1 + trailing_activation_pct)
        else:
            trailing_activation = entry_price * (1 - trailing_activation_pct)
        
        # 6. Calculate stop loss if ATR provided
        stop_loss = None
        if atr is not None:
            atr_buffer = atr * 1.5  # 1.5x ATR for stop
            if side in ['long', 'buy']:
                stop_loss = entry_price - atr_buffer
            else:
                stop_loss = entry_price + atr_buffer
        
        # 7. Compile results
        result = {
            'targets': adaptive_targets,
            'trailing_activation': trailing_activation,
            'trailing_activation_pct': trailing_activation_pct,
            'trend_strength': trend_strength.value,
            'trend_multiplier': trend_mult,
            'volatility_regime': current_regime,
            'volatility_multiplier': vol_mult,
            'has_divergence': has_divergence,
            'divergence_penalty': divergence_penalty,
            'combined_multiplier': combined_multiplier,
            'metrics': trend_metrics,
        }
        
        logger.info(f"📊 Adaptive Profit Targets ({side.upper()}):")
        logger.info(f"   Entry: ${entry_price:.4f}")
        logger.info(f"   Trend: {trend_strength.value.upper()} ({trend_mult:.1f}x)")
        logger.info(f"   Volatility: {current_regime.upper()} ({vol_mult:.1f}x)")
        logger.info(f"   Divergence: {'YES' if has_divergence else 'NO'} ({divergence_penalty:.2f}x)")
        logger.info(f"   Combined Multiplier: {combined_multiplier:.2f}x")
        logger.info(f"   TP1: ${adaptive_targets['tp1']['price']:.4f} ({adaptive_targets['tp1']['percentage']*100:.2f}%)")
        logger.info(f"   TP2: ${adaptive_targets['tp2']['price']:.4f} ({adaptive_targets['tp2']['percentage']*100:.2f}%)")
        logger.info(f"   TP3: ${adaptive_targets['tp3']['price']:.4f} ({adaptive_targets['tp3']['percentage']*100:.2f}%)")
        
        return result
    
    def _assess_trend_strength(self, indicators: Dict) -> Tuple[TrendStrength, Dict]:
        """
        Assess current trend strength based on ADX and other indicators
        
        Args:
            indicators: Dictionary of calculated indicators
            
        Returns:
            Tuple of (TrendStrength enum, metrics dict)
        """
        # Get ADX value
        adx_series = indicators.get('adx', pd.Series([0]))
        if len(adx_series) == 0:
            return TrendStrength.WEAK, {'adx': 0}
        
        adx = float(adx_series.iloc[-1])
        
        # Classify trend strength based on ADX
        if adx >= 50:
            strength = TrendStrength.EXTREME
        elif adx >= 35:
            strength = TrendStrength.STRONG
        elif adx >= 25:
            strength = TrendStrength.MODERATE
        else:
            strength = TrendStrength.WEAK
        
        # Additional trend confirmation indicators
        plus_di = float(indicators.get('plus_di', pd.Series([0])).iloc[-1]) if 'plus_di' in indicators else 0
        minus_di = float(indicators.get('minus_di', pd.Series([0])).iloc[-1]) if 'minus_di' in indicators else 0
        
        # DI spread (larger spread = stronger trend)
        di_spread = abs(plus_di - minus_di)
        
        metrics = {
            'adx': adx,
            'plus_di': plus_di,
            'minus_di': minus_di,
            'di_spread': di_spread,
            'strength': strength.value,
        }
        
        return strength, metrics
    
    def _detect_momentum_divergence(
        self,
        df: pd.DataFrame,
        indicators: Dict
    ) -> Tuple[bool, float]:
        """
        Detect momentum divergence (price making new highs/lows but indicators not confirming)
        
        Divergence signals weakening momentum and suggests tighter profit targets.
        
        Args:
            df: Price DataFrame
            indicators: Dictionary of indicators
            
        Returns:
            Tuple of (has_divergence, divergence_score)
        """
        if len(df) < 20:
            return False, 0.0
        
        # Get recent price action
        recent_df = df.tail(20)
        close_prices = recent_df['close']
        
        # Get MACD histogram (momentum proxy)
        macd_hist = indicators.get('histogram', pd.Series([0]))
        if len(macd_hist) < 20:
            return False, 0.0
        
        recent_macd = macd_hist.tail(20)
        
        # Check for bullish divergence (price lower lows, MACD higher lows)
        # Compare current to previous 10 (excluding current)
        price_making_lower_lows = close_prices.iloc[-1] < close_prices.iloc[-10:-1].min()
        macd_making_higher_lows = recent_macd.iloc[-1] > recent_macd.iloc[-10:-1].min()
        
        bullish_divergence = price_making_lower_lows and macd_making_higher_lows
        
        # Check for bearish divergence (price higher highs, MACD lower highs)
        # Compare current to previous 10 (excluding current)
        price_making_higher_highs = close_prices.iloc[-1] > close_prices.iloc[-10:-1].max()
        macd_making_lower_highs = recent_macd.iloc[-1] < recent_macd.iloc[-10:-1].max()
        
        bearish_divergence = price_making_higher_highs and macd_making_lower_highs
        
        has_divergence = bullish_divergence or bearish_divergence
        
        # Calculate divergence score (0.0 to 1.0)
        if has_divergence:
            # Measure the magnitude of divergence
            price_range = close_prices.max() - close_prices.min()
            macd_range = recent_macd.max() - recent_macd.min()
            
            if price_range > 0 and macd_range > 0:
                # Normalized divergence strength
                divergence_score = min(1.0, abs(
                    (close_prices.iloc[-1] - close_prices.iloc[-10]) / price_range -
                    (recent_macd.iloc[-1] - recent_macd.iloc[-10]) / macd_range
                ))
            else:
                divergence_score = 0.5  # Default moderate divergence
        else:
            divergence_score = 0.0
        
        if has_divergence:
            logger.debug(f"⚠️  Momentum divergence detected (score: {divergence_score:.2f})")
        
        return has_divergence, divergence_score
    
    def should_exit_at_target(
        self,
        current_price: float,
        entry_price: float,
        side: str,
        adaptive_targets: Dict,
        exits_taken: List[str] = None
    ) -> Tuple[bool, Optional[str], Optional[float]]:
        """
        Check if current price has reached any profit target
        
        Args:
            current_price: Current market price
            entry_price: Position entry price
            side: 'long' or 'short'
            adaptive_targets: Dictionary of adaptive targets
            exits_taken: List of target levels already taken
            
        Returns:
            Tuple of (should_exit, target_level, exit_percentage)
        """
        if exits_taken is None:
            exits_taken = []
        
        targets = adaptive_targets.get('targets', {})
        
        # Check each target level in order
        for level in ['tp1', 'tp2', 'tp3', 'tp4', 'tp5']:
            if level not in targets or level in exits_taken:
                continue
            
            target_info = targets[level]
            target_price = target_info['price']
            
            # Normalize side parameter
            side_norm = side.lower()
            
            # Check if target reached
            target_reached = False
            if side_norm in ['long', 'buy']:
                target_reached = current_price >= target_price
            else:  # short
                target_reached = current_price <= target_price
            
            if target_reached:
                exit_pct = target_info['exit_pct']
                logger.info(f"✅ Profit target {level.upper()} reached: ${target_price:.4f} (exit {exit_pct*100:.0f}%)")
                return True, level, exit_pct
        
        return False, None, None
    
    def get_profit_target_summary(self, adaptive_targets: Dict) -> str:
        """
        Generate human-readable summary of adaptive profit targets
        
        Args:
            adaptive_targets: Dictionary of adaptive targets
            
        Returns:
            Formatted summary string
        """
        targets = adaptive_targets.get('targets', {})
        
        lines = [
            "\n" + "=" * 70,
            "ADAPTIVE PROFIT TARGETS",
            "=" * 70,
            f"Trend Strength: {adaptive_targets.get('trend_strength', 'N/A').upper()}",
            f"Volatility Regime: {adaptive_targets.get('volatility_regime', 'N/A').upper()}",
            f"Combined Multiplier: {adaptive_targets.get('combined_multiplier', 1.0):.2f}x",
            f"Divergence Detected: {'YES' if adaptive_targets.get('has_divergence', False) else 'NO'}",
            "",
            "📈 Profit Target Levels:",
        ]
        
        for level in ['tp1', 'tp2', 'tp3', 'tp4', 'tp5']:
            if level in targets:
                info = targets[level]
                lines.append(
                    f"  {level.upper()}: ${info['price']:.4f} "
                    f"(+{info['percentage']*100:.2f}%) - "
                    f"Exit {info['exit_pct']*100:.0f}%"
                )
        
        lines.append(f"\n🎯 Trailing Stop Activation: ${adaptive_targets.get('trailing_activation', 0):.4f}")
        lines.append("=" * 70)
        
        return "\n".join(lines)


def get_adaptive_profit_engine(config: Dict = None) -> AdaptiveProfitTargetEngine:
    """
    Factory function to create AdaptiveProfitTargetEngine instance
    
    Args:
        config: Optional configuration dictionary
        
    Returns:
        AdaptiveProfitTargetEngine instance
    """
    return AdaptiveProfitTargetEngine(config)


# Example usage and testing
if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
    
    # Create sample data
    dates = pd.date_range('2024-01-01', periods=100, freq='5T')
    df = pd.DataFrame({
        'timestamp': dates,
        'close': np.random.randn(100).cumsum() + 100,
        'high': np.random.randn(100).cumsum() + 102,
        'low': np.random.randn(100).cumsum() + 98,
        'volume': np.random.randint(1000, 10000, 100)
    })
    
    # Mock indicators
    indicators = {
        'adx': pd.Series(np.random.uniform(20, 40, 100)),
        'plus_di': pd.Series(np.random.uniform(15, 35, 100)),
        'minus_di': pd.Series(np.random.uniform(10, 30, 100)),
        'histogram': pd.Series(np.random.randn(100)),
    }
    
    # Create engine
    engine = get_adaptive_profit_engine()
    
    # Calculate adaptive targets
    entry_price = 100.0
    targets = engine.calculate_adaptive_targets(
        entry_price=entry_price,
        side='long',
        df=df,
        indicators=indicators,
        current_regime='normal'
    )
    
    # Print summary
    print(engine.get_profit_target_summary(targets))
    
    # Simulate price movement and check exits
    current_price = 101.5
    should_exit, level, exit_pct = engine.should_exit_at_target(
        current_price=current_price,
        entry_price=entry_price,
        side='long',
        adaptive_targets=targets
    )
    
    if should_exit:
        print(f"\n✅ Exit signal: {level.upper()} - Exit {exit_pct*100:.0f}% of position")
    else:
        print(f"\n⏳ No exit yet at ${current_price:.2f}")
