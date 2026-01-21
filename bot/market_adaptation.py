# bot/market_adaptation.py
"""
NIJA Market Adaptation & Learning System
Dynamically adapts trading strategy to market conditions for consistent profitability

Features:
- Real-time market regime detection (trending/ranging/choppy)
- Automatic strategy parameter adjustment
- Learning from past trades
- Volatility-based pair selection
- Liquidity filtering
- Adaptive profit targets and stop losses

Version: 1.0
Date: December 30, 2025
"""

import logging
import json
import os
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from enum import Enum

# Import scalar helper for indicator conversions
try:
    from indicators import scalar
except ImportError:
    # Fallback if indicators.py is not available
    def scalar(x):
        if isinstance(x, (tuple, list)):
            return float(x[0])
        return float(x)

logger = logging.getLogger("nija.market_adaptation")


class MarketRegime(Enum):
    """Current market regime"""
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    CHOPPY = "choppy"
    VOLATILE = "volatile"
    QUIET = "quiet"


@dataclass
class MarketMetrics:
    """Metrics for market condition analysis"""
    volatility: float = 0.0  # ATR as % of price
    trend_strength: float = 0.0  # ADX value
    volume_ratio: float = 1.0  # Current volume / avg volume
    price_momentum: float = 0.0  # ROC (Rate of Change)
    liquidity_score: float = 0.0  # Bid-ask spread, depth
    regime: MarketRegime = MarketRegime.RANGING
    
    def to_dict(self) -> Dict:
        return {
            **asdict(self),
            'regime': self.regime.value
        }


@dataclass
class AdaptiveParameters:
    """Strategy parameters that adapt to market conditions"""
    position_size_multiplier: float = 1.0
    profit_target_multiplier: float = 1.0
    stop_loss_multiplier: float = 1.0
    signal_threshold: int = 3
    max_positions: int = 8
    scan_interval_seconds: int = 15
    
    def to_dict(self) -> Dict:
        return asdict(self)


class MarketAdaptationEngine:
    """
    Adapts trading strategy to current market conditions
    
    Key adaptations:
    1. Trending markets: Larger positions, wider stops, higher targets
    2. Ranging markets: Smaller positions, tighter stops, quick exits
    3. Choppy markets: Reduce trading, strict filters, minimal positions
    4. Volatile markets: Adjust for wider price swings
    5. Quiet markets: Wait for better opportunities
    """
    
    def __init__(self, learning_enabled: bool = True):
        """
        Initialize market adaptation engine
        
        Args:
            learning_enabled: If True, learns from past trades to improve
        """
        self.learning_enabled = learning_enabled
        
        # Load historical performance by regime
        self.performance_file = "market_regime_performance.json"
        self.performance_history = self._load_performance_history()
        
        # Current market state
        self.current_regime = MarketRegime.RANGING
        self.current_metrics = MarketMetrics()
        self.current_parameters = AdaptiveParameters()
        
        logger.info(f"✅ Market adaptation engine initialized")
        logger.info(f"   Learning: {'enabled' if learning_enabled else 'disabled'}")
    
    def _load_performance_history(self) -> Dict:
        """Load historical performance by market regime"""
        try:
            if os.path.exists(self.performance_file):
                with open(self.performance_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load performance history: {e}")
        
        # Initialize with empty history for each regime
        return {regime.value: {
            'trades': 0,
            'wins': 0,
            'losses': 0,
            'total_pnl': 0.0,
            'avg_hold_time_minutes': 0,
            'best_parameters': None
        } for regime in MarketRegime}
    
    def _save_performance_history(self):
        """Save performance history to file"""
        try:
            with open(self.performance_file, 'w') as f:
                json.dump(self.performance_history, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save performance history: {e}")
    
    def analyze_market_regime(self, market_data: pd.DataFrame, 
                            symbol: str) -> Tuple[MarketRegime, MarketMetrics]:
        """
        Analyze current market regime from price data
        
        Args:
            market_data: DataFrame with OHLCV data
            symbol: Market symbol (e.g., 'BTC-USD')
        
        Returns:
            Tuple of (regime, metrics)
        """
        if len(market_data) < 50:
            return MarketRegime.RANGING, MarketMetrics()
        
        # Calculate metrics
        metrics = MarketMetrics()
        
        # 1. Volatility (ATR as % of price)
        high_low = market_data['high'] - market_data['low']
        high_close = abs(market_data['high'] - market_data['close'].shift(1))
        low_close = abs(market_data['low'] - market_data['close'].shift(1))
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = true_range.rolling(14).mean().iloc[-1]
        current_price = market_data['close'].iloc[-1]
        metrics.volatility = (atr / current_price) * 100 if current_price > 0 else 0
        
        # 2. Trend strength (ADX)
        # Simplified ADX calculation
        plus_dm = market_data['high'].diff()
        minus_dm = -market_data['low'].diff()
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm < 0] = 0
        
        atr_series = true_range.rolling(14).mean()
        plus_di = 100 * (plus_dm.rolling(14).mean() / atr_series)
        minus_di = 100 * (minus_dm.rolling(14).mean() / atr_series)
        
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di + 0.0001)
        adx = dx.rolling(14).mean().iloc[-1]
        metrics.trend_strength = scalar(adx) if not np.isnan(adx) else 0
        
        # 3. Volume ratio
        avg_volume = market_data['volume'].rolling(20).mean().iloc[-1]
        current_volume = market_data['volume'].iloc[-1]
        metrics.volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0
        
        # 4. Price momentum (ROC)
        roc_period = 10
        if len(market_data) > roc_period:
            price_change = market_data['close'].iloc[-1] - market_data['close'].iloc[-roc_period]
            metrics.price_momentum = (price_change / market_data['close'].iloc[-roc_period]) * 100
        
        # 5. Determine regime
        regime = self._classify_regime(metrics, scalar(plus_di.iloc[-1]), scalar(minus_di.iloc[-1]))
        metrics.regime = regime
        
        # Update current state
        self.current_regime = regime
        self.current_metrics = metrics
        
        logger.debug(f"{symbol}: Regime={regime.value}, ADX={metrics.trend_strength:.1f}, "
                    f"Vol={metrics.volatility:.2f}%, Mom={metrics.price_momentum:+.2f}%")
        
        return regime, metrics
    
    def _classify_regime(self, metrics: MarketMetrics, 
                        plus_di: float, minus_di: float) -> MarketRegime:
        """
        Classify market regime based on metrics
        
        Args:
            metrics: Market metrics
            plus_di: Positive directional indicator
            minus_di: Negative directional indicator
        
        Returns:
            Market regime classification
        """
        adx = scalar(metrics.trend_strength)
        volatility = scalar(metrics.volatility)
        volume_ratio = scalar(metrics.volume_ratio)
        
        # High volatility, low volume = Choppy
        if volatility > 3.0 and volume_ratio < 0.8:
            return MarketRegime.CHOPPY
        
        # Very low volatility = Quiet
        if volatility < 0.5:
            return MarketRegime.QUIET
        
        # Very high volatility = Volatile
        if volatility > 5.0:
            return MarketRegime.VOLATILE
        
        # Strong trend (ADX > 30)
        if adx > 30:
            if plus_di > minus_di:
                return MarketRegime.TRENDING_UP
            else:
                return MarketRegime.TRENDING_DOWN
        
        # Weak trend (ADX < 20) = Ranging
        if adx < 20:
            return MarketRegime.RANGING
        
        # Medium trend (20-30) - determine direction
        if plus_di > minus_di * 1.2:
            return MarketRegime.TRENDING_UP
        elif minus_di > plus_di * 1.2:
            return MarketRegime.TRENDING_DOWN
        else:
            return MarketRegime.RANGING
    
    def get_adapted_parameters(self, account_balance: float, 
                              capital_tier: int = 3) -> AdaptiveParameters:
        """
        Get strategy parameters adapted to current market regime
        
        Args:
            account_balance: Current account balance
            capital_tier: Capital tier (1-6) from CAPITAL_SCALING_PLAYBOOK
        
        Returns:
            Adapted parameters for current regime
        """
        params = AdaptiveParameters()
        regime = self.current_regime
        
        # Base parameters by regime
        if regime == MarketRegime.TRENDING_UP or regime == MarketRegime.TRENDING_DOWN:
            # Trending: Larger positions, wider stops, trail profits
            params.position_size_multiplier = 1.2
            params.profit_target_multiplier = 1.5  # Let winners run
            params.stop_loss_multiplier = 1.5  # Wider stops
            params.signal_threshold = 3  # Moderate filter
            params.max_positions = min(10, 8 + capital_tier)
            params.scan_interval_seconds = 15
            
        elif regime == MarketRegime.RANGING:
            # Ranging: Normal parameters, quick in/out
            params.position_size_multiplier = 1.0
            params.profit_target_multiplier = 1.0
            params.stop_loss_multiplier = 1.0
            params.signal_threshold = 3
            params.max_positions = 8
            params.scan_interval_seconds = 15
            
        elif regime == MarketRegime.CHOPPY:
            # Choppy: Reduce trading, strict filters, small positions
            params.position_size_multiplier = 0.5
            params.profit_target_multiplier = 0.8  # Quick exits
            params.stop_loss_multiplier = 0.8  # Tight stops
            params.signal_threshold = 4  # Very strict
            params.max_positions = max(3, 8 - capital_tier)
            params.scan_interval_seconds = 30  # Less frequent
            
        elif regime == MarketRegime.VOLATILE:
            # Volatile: Adjust for wider swings
            params.position_size_multiplier = 0.7
            params.profit_target_multiplier = 2.0  # Bigger swings
            params.stop_loss_multiplier = 2.0  # Much wider stops
            params.signal_threshold = 4
            params.max_positions = 6
            params.scan_interval_seconds = 20
            
        elif regime == MarketRegime.QUIET:
            # Quiet: Wait for better conditions, minimal trading
            params.position_size_multiplier = 0.3
            params.profit_target_multiplier = 0.5
            params.stop_loss_multiplier = 0.5
            params.signal_threshold = 5  # Extremely strict
            params.max_positions = 2
            params.scan_interval_seconds = 60  # Wait for action
        
        # Apply learning adjustments if enabled
        if self.learning_enabled:
            params = self._apply_learned_adjustments(params, regime)
        
        # Update current parameters
        self.current_parameters = params
        
        logger.info(f"📊 Adapted parameters for {regime.value}:")
        logger.info(f"   Position size: {params.position_size_multiplier}x")
        logger.info(f"   Profit target: {params.profit_target_multiplier}x")
        logger.info(f"   Stop loss: {params.stop_loss_multiplier}x")
        logger.info(f"   Signal threshold: {params.signal_threshold}/5")
        logger.info(f"   Max positions: {params.max_positions}")
        
        return params
    
    def _apply_learned_adjustments(self, params: AdaptiveParameters, 
                                   regime: MarketRegime) -> AdaptiveParameters:
        """Apply learned adjustments from historical performance"""
        
        regime_history = self.performance_history.get(regime.value, {})
        
        # If we have enough data, apply learned best parameters
        if regime_history.get('trades', 0) >= 20:
            win_rate = regime_history['wins'] / regime_history['trades']
            
            # If win rate is low in this regime, be more conservative
            if win_rate < 0.5:
                params.position_size_multiplier *= 0.8
                params.signal_threshold = min(5, params.signal_threshold + 1)
                logger.info(f"   📉 Learning: Low win rate ({win_rate:.1%}) in {regime.value}, "
                          f"reducing aggression")
            
            # If win rate is high, can be more aggressive
            elif win_rate > 0.7:
                params.position_size_multiplier *= 1.1
                logger.info(f"   📈 Learning: High win rate ({win_rate:.1%}) in {regime.value}, "
                          f"increasing aggression")
        
        return params
    
    def record_trade_performance(self, regime: MarketRegime, 
                                pnl_dollars: float, 
                                hold_time_minutes: int,
                                parameters_used: Dict):
        """
        Record trade performance for learning
        
        Args:
            regime: Market regime when trade was executed
            pnl_dollars: Profit/loss in dollars
            hold_time_minutes: How long position was held
            parameters_used: Strategy parameters used for this trade
        """
        if not self.learning_enabled:
            return
        
        regime_key = regime.value
        history = self.performance_history[regime_key]
        
        # Update counters
        history['trades'] += 1
        if pnl_dollars > 0:
            history['wins'] += 1
        else:
            history['losses'] += 1
        
        # Update totals
        history['total_pnl'] += pnl_dollars
        
        # Update average hold time
        total_hold_time = history['avg_hold_time_minutes'] * (history['trades'] - 1)
        history['avg_hold_time_minutes'] = (total_hold_time + hold_time_minutes) / history['trades']
        
        # Save best parameters if this regime is performing well
        win_rate = history['wins'] / history['trades']
        if win_rate > 0.6 and history['trades'] >= 10:
            history['best_parameters'] = parameters_used
        
        # Save to file
        self._save_performance_history()
        
        logger.debug(f"Recorded trade in {regime.value}: "
                    f"${pnl_dollars:+.2f}, {hold_time_minutes}min hold")
    
    def select_best_markets(self, market_candidates: List[str],
                          market_data_dict: Dict[str, pd.DataFrame],
                          top_n: int = 20) -> List[Tuple[str, float]]:
        """
        Select best markets to trade based on current conditions
        
        Args:
            market_candidates: List of market symbols to consider
            market_data_dict: Dict of symbol -> DataFrame with OHLCV data
            top_n: Number of top markets to return
        
        Returns:
            List of (symbol, score) tuples, sorted by score (best first)
        """
        scored_markets = []
        
        for symbol in market_candidates:
            if symbol not in market_data_dict:
                continue
            
            df = market_data_dict[symbol]
            if len(df) < 50:
                continue
            
            # Analyze regime
            regime, metrics = self.analyze_market_regime(df, symbol)
            
            # Calculate opportunity score
            score = self._calculate_opportunity_score(regime, metrics, symbol)
            
            if score > 0:
                scored_markets.append((symbol, score))
        
        # Sort by score (highest first)
        scored_markets.sort(key=lambda x: x[1], reverse=True)
        
        # Return top N
        top_markets = scored_markets[:top_n]
        
        if top_markets:
            logger.info(f"🎯 Top {len(top_markets)} market opportunities:")
            for i, (symbol, score) in enumerate(top_markets[:5], 1):
                logger.info(f"   {i}. {symbol}: {score:.2f}")
        
        return top_markets
    
    def _calculate_opportunity_score(self, regime: MarketRegime, 
                                     metrics: MarketMetrics,
                                     symbol: str) -> float:
        """
        Calculate opportunity score for a market
        
        Higher score = better opportunity
        
        Factors:
        - Regime favorability (trending > ranging > choppy)
        - Volume (higher is better)
        - Volatility (moderate is best)
        - Historical performance in this regime
        """
        score = 0.0
        
        # 1. Regime score (40 points max)
        regime_scores = {
            MarketRegime.TRENDING_UP: 40,
            MarketRegime.TRENDING_DOWN: 40,
            MarketRegime.RANGING: 25,
            MarketRegime.VOLATILE: 20,
            MarketRegime.CHOPPY: 5,
            MarketRegime.QUIET: 0,
        }
        score += regime_scores.get(regime, 0)
        
        # 2. Trend strength (20 points max)
        # Strong trends (ADX > 30) get full points
        score += min(20, (metrics.trend_strength / 30) * 20)
        
        # 3. Volume score (20 points max)
        # 1.5x average volume = full points
        score += min(20, (metrics.volume_ratio / 1.5) * 20)
        
        # 4. Volatility score (10 points max)
        # Optimal volatility: 1-3%
        if 1.0 <= metrics.volatility <= 3.0:
            score += 10
        elif 0.5 <= metrics.volatility < 1.0 or 3.0 < metrics.volatility <= 5.0:
            score += 5
        # Too low or too high = 0 points
        
        # 5. Historical performance (10 points max)
        if self.learning_enabled:
            regime_history = self.performance_history.get(regime.value, {})
            if regime_history.get('trades', 0) >= 10:
                win_rate = regime_history['wins'] / regime_history['trades']
                score += win_rate * 10
        
        return score
    
    def get_market_summary(self) -> Dict:
        """Get summary of current market conditions"""
        return {
            'current_regime': self.current_regime.value,
            'metrics': self.current_metrics.to_dict(),
            'parameters': self.current_parameters.to_dict(),
            'regime_performance': self.performance_history,
        }


# Convenience function
def create_market_adapter(learning_enabled: bool = True) -> MarketAdaptationEngine:
    """
    Create market adaptation engine
    
    Args:
        learning_enabled: Enable learning from past trades
    
    Returns:
        MarketAdaptationEngine instance
    """
    return MarketAdaptationEngine(learning_enabled=learning_enabled)


# Example usage
if __name__ == "__main__":
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(message)s'
    )
    
    # Create adapter
    adapter = create_market_adapter(learning_enabled=True)
    
    # Simulate market data
    dates = pd.date_range(start='2025-01-01', periods=100, freq='5min')
    prices = np.cumsum(np.random.randn(100)) + 50000  # Random walk starting at 50k
    
    df = pd.DataFrame({
        'timestamp': dates,
        'open': prices,
        'high': prices + np.random.rand(100) * 100,
        'low': prices - np.random.rand(100) * 100,
        'close': prices,
        'volume': np.random.rand(100) * 1000000
    })
    
    # Analyze regime
    regime, metrics = adapter.analyze_market_regime(df, "BTC-USD")
    
    print(f"\nMarket Regime: {regime.value}")
    print(f"Metrics: {json.dumps(metrics.to_dict(), indent=2)}")
    
    # Get adapted parameters
    params = adapter.get_adapted_parameters(account_balance=1000, capital_tier=3)
    print(f"\nAdapted Parameters: {json.dumps(params.to_dict(), indent=2)}")
    
    # Record some sample trades
    adapter.record_trade_performance(regime, pnl_dollars=15.50, hold_time_minutes=25, 
                                    parameters_used=params.to_dict())
    
    # Get summary
    summary = adapter.get_market_summary()
    print(f"\nMarket Summary: {json.dumps(summary, indent=2)}")
