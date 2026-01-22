# enhanced_strategy_config.py
"""
Enhanced Strategy Configuration for NIJA AI Trading Bot
Based on 2026 cryptocurrency trading research

This configuration enables multi-indicator consensus trading with market regime detection
for significantly improved profitability (+15-25% win rate improvement expected).

Research Source: STRATEGY_RESEARCH_2026.md
"""

# ===================================================================
# MULTI-INDICATOR CONSENSUS SCORING
# ===================================================================

# Minimum score required to enter a trade (0-10 scale)
# Research shows 73% win rate with score >= 7 vs 45-50% with single indicators
MIN_ENTRY_SCORE = 5  # Conservative: Require at least 5/10 points
OPTIMAL_ENTRY_SCORE = 7  # Optimal: Target 7/10 points for best trades
MAX_ENTRY_SCORE = 10  # Maximum possible score

# Score-based position sizing
# Higher confidence = larger position size
POSITION_SIZE_BY_SCORE = {
    10: 1.0,   # 100% of calculated position size
    9: 1.0,    # 100%
    8: 0.9,    # 90%
    7: 0.8,    # 80%
    6: 0.7,    # 70%
    5: 0.5,    # 50%
    4: 0.0,    # Skip trade
    3: 0.0,    # Skip trade
    2: 0.0,    # Skip trade
    1: 0.0,    # Skip trade
    0: 0.0     # Skip trade
}

# ===================================================================
# MARKET REGIME DETECTION
# ===================================================================

# ADX thresholds for regime detection
ADX_TRENDING_THRESHOLD = 25   # Above = trending market (use momentum)
ADX_RANGING_THRESHOLD = 20    # Below = ranging market (use mean reversion)

# Bollinger Band Width thresholds for volatility detection
BB_LOW_VOLATILITY_THRESHOLD = 0.05   # Below = low volatility (breakout prep)
BB_HIGH_VOLATILITY_THRESHOLD = 0.15  # Above = high volatility (reduce risk)

# Strategy selection by regime
REGIME_STRATEGIES = {
    'TRENDING': 'momentum',        # Use RSI + MACD momentum in trends
    'RANGING': 'mean_reversion',   # Use Bollinger Bands mean reversion in ranges
    'TRANSITIONAL': 'cautious'     # Reduce position sizes during transitions
}

# Position size multipliers by regime
REGIME_POSITION_MULTIPLIERS = {
    'TRENDING': 1.0,       # Full position size in strong trends
    'RANGING': 0.8,        # Reduced position size in ranges (more risk)
    'TRANSITIONAL': 0.5    # Half position size during transitions
}

# Volatility-based position multipliers
VOLATILITY_POSITION_MULTIPLIERS = {
    'LOW': 1.2,      # Increase position size in low volatility (breakouts)
    'MEDIUM': 1.0,   # Normal position size
    'HIGH': 0.7      # Reduce position size in high volatility (more risk)
}

# ===================================================================
# INDICATOR SETTINGS
# ===================================================================

# RSI Settings
RSI_PERIOD = 14
RSI_FAST_PERIOD = 9
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70

# MACD Settings
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# Stochastic Settings
STOCH_K_PERIOD = 14
STOCH_D_PERIOD = 3
STOCH_OVERSOLD = 20
STOCH_OVERBOUGHT = 80

# Bollinger Bands Settings
BB_PERIOD = 20
BB_STD_DEV = 2.0

# EMA Settings
EMA_FAST = 9
EMA_MEDIUM = 21
EMA_SLOW = 50

# VWAP Settings
VWAP_STD_DEV = 2.0

# ADX Settings
ADX_PERIOD = 14

# ATR Settings (for stop loss)
ATR_PERIOD = 14
ATR_STOP_LOSS_MULTIPLIER = 2.0  # Stop loss at 2x ATR

# Volume Settings
VOLUME_SURGE_THRESHOLD = 1.2   # 120% of average = surge
VOLUME_MIN_THRESHOLD = 0.8     # 80% of average = minimum acceptable

# ===================================================================
# MOMENTUM STRATEGY (For Trending Markets)
# ===================================================================

MOMENTUM_CONFIG = {
    'name': 'momentum',
    'description': 'RSI + MACD + Stochastic momentum strategy for trending markets',
    
    # Entry conditions (all must be true)
    'entry_conditions': {
        'min_adx': 25,                    # Strong trend required
        'rsi_range': (30, 70),            # Avoid extreme RSI
        'macd_histogram_rising': True,    # MACD momentum building
        'price_above_vwap': True,         # Bullish bias
        'ema_alignment': True,            # EMA 9 > 21 > 50
        'volume_surge': True,             # Volume confirmation
        'min_score': 7                    # High confidence required
    },
    
    # Exit conditions
    'exit_conditions': {
        'opposite_signal': True,          # Exit on opposite entry signal
        'trailing_stop': True,            # Use ATR-based trailing stop
        'profit_target_pct': 2.0,         # 2% profit target
        'max_hold_minutes': 120           # Max 2 hours hold time
    },
    
    # Position sizing
    'position_size': {
        'base_pct': 0.10,                 # 10% of capital base
        'max_pct': 0.20,                  # 20% maximum (with high confidence)
        'scale_by_score': True,           # Scale based on entry score
        'scale_by_adx': True              # Increase size with stronger trends
    }
}

# ===================================================================
# MEAN REVERSION STRATEGY (For Ranging Markets)
# ===================================================================

MEAN_REVERSION_CONFIG = {
    'name': 'mean_reversion',
    'description': 'Bollinger Bands + RSI mean reversion for ranging markets',
    
    # Entry conditions
    'entry_conditions': {
        'max_adx': 20,                         # Weak trend (ranging)
        'price_at_bollinger_band': True,       # Price touching bands
        'rsi_extreme': True,                   # RSI < 30 or > 70
        'stochastic_extreme': True,            # Stochastic confirming
        'min_score': 5                         # Medium confidence acceptable
    },
    
    # Exit conditions
    'exit_conditions': {
        'return_to_mean': True,                # Exit at middle Bollinger Band
        'opposite_extreme': True,              # Exit when reaching opposite band
        'profit_target_pct': 1.5,              # 1.5% profit target (smaller than momentum)
        'max_hold_minutes': 60                 # Max 1 hour hold time
    },
    
    # Position sizing
    'position_size': {
        'base_pct': 0.08,                      # 8% of capital base (more conservative)
        'max_pct': 0.15,                       # 15% maximum
        'scale_by_score': True,
        'scale_by_bandwidth': True             # Larger size when bands narrow
    }
}

# ===================================================================
# SCALPING STRATEGY (Optional - For Experienced Users)
# ===================================================================

SCALPING_CONFIG = {
    'name': 'scalping',
    'description': 'Ultra-fast scalping for high-liquidity pairs',
    'enabled': False,  # Disabled by default - requires opt-in
    
    # Entry conditions (very tight)
    'entry_conditions': {
        'min_liquidity': 1000000,              # $1M+ daily volume required
        'tight_spread': 0.001,                 # 0.1% max spread
        'momentum_confirmation': True,          # Quick momentum spike
        'min_score': 8                         # Very high confidence
    },
    
    # Exit conditions (very tight)
    'exit_conditions': {
        'profit_target_pct': 0.3,              # 0.3% profit target
        'stop_loss_pct': 0.2,                  # 0.2% stop loss
        'max_hold_seconds': 180                # Max 3 minutes hold
    },
    
    # Position sizing
    'position_size': {
        'base_pct': 0.05,                      # 5% of capital (very conservative)
        'max_pct': 0.10,                       # 10% maximum
        'fee_adjusted': True                   # Account for trading fees
    },
    
    # Risk management
    'risk_management': {
        'max_trades_per_hour': 20,             # Limit overtrading
        'max_daily_loss_pct': 2.0,             # 2% max daily loss
        'require_low_fees': True               # Only on low-fee exchanges
    }
}

# ===================================================================
# RISK MANAGEMENT
# ===================================================================

RISK_CONFIG = {
    # Per-trade risk limits
    'max_risk_per_trade_pct': 2.0,         # Never risk more than 2% per trade
    'max_position_size_pct': 20.0,          # Never exceed 20% of capital
    'min_position_size_usd': 2.0,           # Minimum $2 position (lowered from $5)
    
    # Portfolio risk limits
    'max_total_exposure_pct': 50.0,         # Max 50% of capital in positions
    'max_concurrent_positions': 5,          # Max 5 positions at once
    'min_reserve_pct': 10.0,                # Keep 10% cash reserve
    
    # Stop loss settings
    'use_atr_stop_loss': True,              # Use ATR-based dynamic stops
    'atr_multiplier': 2.0,                  # 2x ATR for stop loss
    'max_stop_loss_pct': 3.0,               # Never exceed 3% stop loss
    'trailing_stop_enabled': True,          # Use trailing stops
    'trailing_stop_activation_pct': 1.0,    # Activate after 1% profit
    'trailing_stop_distance_pct': 0.5,      # Trail 0.5% below peak
    
    # Time-based exits
    'max_losing_hold_minutes': 15,          # Exit losing trades after 15 min
    'max_winning_hold_hours': 4,            # Exit winning trades after 4 hours
    
    # Emergency controls
    'emergency_liquidation_enabled': True,  # Emergency liquidation on extreme moves
    'emergency_loss_threshold_pct': 5.0,    # Liquidate if position down 5%
    'circuit_breaker_daily_loss_pct': 10.0  # Stop trading if daily loss exceeds 10%
}

# ===================================================================
# BACKTESTING & OPTIMIZATION
# ===================================================================

BACKTEST_CONFIG = {
    'initial_capital': 1000.0,              # $1,000 starting capital
    'commission_pct': 0.001,                # 0.1% commission (Kraken)
    'slippage_pct': 0.0005,                 # 0.05% slippage
    'min_data_periods': 100,                # Minimum candles for indicators
    'test_period_days': 90,                 # Test on 90 days of data
    'validation_split': 0.3                 # 30% validation set
}

# ===================================================================
# PERFORMANCE TARGETS (Based on Research)
# ===================================================================

PERFORMANCE_TARGETS = {
    # Conservative estimates (multi-indicator consensus)
    'target_win_rate': 0.70,                # 70% win rate target
    'target_avg_win_pct': 2.0,              # 2.0% average win
    'target_avg_loss_pct': -0.6,            # -0.6% average loss
    'target_profit_factor': 2.5,            # Win $ / Loss $ ratio
    'target_daily_return_pct': 1.5,         # 1.5% daily return
    'target_monthly_return_pct': 25.0,      # 25% monthly return
    
    # Optimistic estimates (all enhancements)
    'optimal_win_rate': 0.80,               # 80% win rate optimal
    'optimal_avg_win_pct': 2.5,             # 2.5% average win
    'optimal_avg_loss_pct': -0.5,           # -0.5% average loss
    'optimal_profit_factor': 4.0,           # 4.0 profit factor
    'optimal_daily_return_pct': 2.5,        # 2.5% daily return
    'optimal_monthly_return_pct': 40.0      # 40% monthly return
}

# ===================================================================
# FEATURE FLAGS
# ===================================================================

FEATURES = {
    'multi_indicator_consensus': True,      # Use multi-indicator scoring
    'market_regime_detection': True,        # Detect market regimes
    'adaptive_strategy_switching': True,    # Switch strategies based on regime
    'confidence_based_sizing': True,        # Scale position by confidence
    'bollinger_bands': True,                # Use Bollinger Bands
    'stochastic_oscillator': True,          # Use Stochastic
    'vwap_bands': True,                     # Use VWAP bands
    'rsi_divergence': False,                # RSI divergence detection (future)
    'macd_histogram_analysis': False,       # MACD histogram slope (future)
    'partial_profit_taking': False,         # Partial exits (future)
    'multi_timeframe': False,               # Multi-timeframe analysis (future)
    'scalping_mode': False                  # Scalping strategy (opt-in)
}

# ===================================================================
# LOGGING & MONITORING
# ===================================================================

LOGGING_CONFIG = {
    'log_level': 'INFO',
    'log_entry_signals': True,              # Log all entry signals
    'log_exit_signals': True,               # Log all exit signals
    'log_regime_changes': True,             # Log market regime changes
    'log_score_breakdown': True,            # Log detailed score breakdown
    'log_performance_metrics': True,        # Log performance metrics
    'save_trades_to_db': True               # Save to trade database
}

# ===================================================================
# USAGE EXAMPLES
# ===================================================================

"""
Example 1: Enable multi-indicator consensus with market regime detection

from bot.enhanced_strategy_config import *

config = {
    'min_entry_score': MIN_ENTRY_SCORE,
    'features': FEATURES,
    'risk': RISK_CONFIG,
    'momentum': MOMENTUM_CONFIG,
    'mean_reversion': MEAN_REVERSION_CONFIG
}

Example 2: Conservative settings for small account

config = {
    'min_entry_score': 7,  # Require very high confidence
    'risk': {
        'max_risk_per_trade_pct': 1.0,  # Only 1% risk per trade
        'max_position_size_pct': 10.0,   # Max 10% per position
        'max_concurrent_positions': 2    # Only 2 positions at once
    }
}

Example 3: Aggressive settings for experienced traders

config = {
    'min_entry_score': 5,  # Accept medium confidence
    'risk': {
        'max_risk_per_trade_pct': 2.0,
        'max_position_size_pct': 20.0,
        'max_concurrent_positions': 5
    },
    'features': {
        'scalping_mode': True  # Enable scalping
    }
}
"""
