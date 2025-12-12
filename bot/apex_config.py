"""
NIJA Apex Strategy v7.1 - Configuration
========================================

All configuration parameters for the Apex trading strategy.
"""

# ═══════════════════════════════════════════════════════════════════
# MARKET FILTER PARAMETERS
# ═══════════════════════════════════════════════════════════════════

MARKET_FILTER = {
    'adx_threshold': 20,  # ADX must be > 20 for trending market
    'adx_strong_threshold': 40,  # ADX > 40 indicates very strong trend
    'volume_threshold': 0.5,  # Volume must be > 50% of recent average
    'volume_lookback': 20,  # Period for average volume calculation
    'trend_required': True,  # Only trade when clear trend (UP or DOWN)
}

# ═══════════════════════════════════════════════════════════════════
# INDICATOR PERIODS
# ═══════════════════════════════════════════════════════════════════

INDICATORS = {
    'ema_fast': 9,
    'ema_medium': 21,
    'ema_slow': 50,
    'rsi_period': 14,
    'rsi_bullish_min': 40,  # RSI bullish zone minimum
    'rsi_bullish_max': 70,  # RSI bullish zone maximum
    'rsi_bearish_min': 30,  # RSI bearish zone minimum
    'rsi_bearish_max': 60,  # RSI bearish zone maximum
    'macd_fast': 12,
    'macd_slow': 26,
    'macd_signal': 9,
    'adx_period': 14,
    'atr_period': 14,
}

# ═══════════════════════════════════════════════════════════════════
# ENTRY TRIGGER PARAMETERS
# ═══════════════════════════════════════════════════════════════════

ENTRY_TRIGGERS = {
    'long': {
        'description': 'Long entry conditions',
        'conditions': [
            'Price pulls to EMA21 or VWAP (within 0.5%)',
            'RSI in bullish zone (40-70)',
            'Bullish reversal candle',
            'MACD histogram uptick (growing)',
            'Volume confirmation (>50% avg)',
        ],
        'required_conditions': 4,  # Minimum 4 out of 5 conditions
        'entry_on_close': True,  # Only enter on candle close
    },
    'short': {
        'description': 'Short entry conditions (mirror of long)',
        'conditions': [
            'Price pulls to EMA21 or VWAP (within 0.5%)',
            'RSI in bearish zone (30-60)',
            'Bearish reversal candle',
            'MACD histogram downtick (shrinking)',
            'Volume confirmation (>50% avg)',
        ],
        'required_conditions': 4,  # Minimum 4 out of 5 conditions
        'entry_on_close': True,  # Only enter on candle close
    },
    'pullback_threshold': 0.005,  # 0.5% distance to EMA21/VWAP for pullback
}

# ═══════════════════════════════════════════════════════════════════
# POSITION SIZING & RISK MANAGEMENT
# ═══════════════════════════════════════════════════════════════════

POSITION_SIZING = {
    'trend_quality': {
        'weak': {
            'adx_range': (20, 25),
            'position_size': 0.02,  # 2% of account
        },
        'good': {
            'adx_range': (25, 30),
            'position_size': 0.05,  # 5% of account
        },
        'strong': {
            'adx_range': (30, 40),
            'position_size': 0.07,  # 7% of account
        },
        'very_strong': {
            'adx_range': (40, 100),
            'position_size': 0.10,  # 10% of account
        },
    },
    'max_position_size': 0.10,  # Hard cap at 10%
    'min_position_size': 0.02,  # Minimum 2%
}

# ═══════════════════════════════════════════════════════════════════
# STOP LOSS PARAMETERS
# ═══════════════════════════════════════════════════════════════════

STOP_LOSS = {
    'method': 'swing_plus_atr',  # Use swing low/high + ATR buffer
    'swing_lookback': 5,  # Look back 5 candles for swing points
    'atr_multiplier': 1.5,  # ATR buffer multiplier
    'min_stop_distance': 0.005,  # Minimum 0.5% stop distance
    'max_stop_distance': 0.02,  # Maximum 2% stop distance
    'always_set_before_entry': True,  # Stop must be set before entry
}

# ═══════════════════════════════════════════════════════════════════
# TAKE PROFIT & TRAILING STOP PARAMETERS
# ═══════════════════════════════════════════════════════════════════

TAKE_PROFIT = {
    'stages': [
        {
            'name': 'TP1',
            'profit_r': 1.0,  # 1R (1x risk)
            'exit_percentage': 0.33,  # Exit 33% of position
            'action': 'move_stop_to_breakeven',
        },
        {
            'name': 'TP2',
            'profit_r': 2.0,  # 2R
            'exit_percentage': 0.33,  # Exit another 33% (66% total)
            'action': 'activate_trailing',
        },
        {
            'name': 'TP3',
            'profit_r': 3.0,  # 3R
            'exit_percentage': 0.34,  # Exit remaining 34% (100% total)
            'action': 'final_exit',
        },
    ],
    'use_multi_stage': True,
}

TRAILING_STOP = {
    'activation_r': 1.0,  # Activate after TP1 (1R profit)
    'atr_multiplier': 1.5,  # Trail at ATR(14) x 1.5
    'update_frequency': 'every_candle',  # Update on each new candle
    'never_widen': True,  # Only tighten, never widen
}

# ═══════════════════════════════════════════════════════════════════
# EXIT LOGIC PARAMETERS
# ═══════════════════════════════════════════════════════════════════

EXIT_LOGIC = {
    'opposite_signal': True,  # Exit on opposite entry signal
    'trailing_stop_hit': True,  # Exit if trailing stop triggered
    'trend_break': {
        'enabled': True,
        'method': 'ema_cross',  # EMA9 crosses EMA21
        'exit_immediately': True,
    },
}

# ═══════════════════════════════════════════════════════════════════
# SMART FILTERS
# ═══════════════════════════════════════════════════════════════════

SMART_FILTERS = {
    'news_blocking': {
        'enabled': True,  # Block trading around news
        'implementation': 'placeholder',  # Placeholder for future
        'cooldown_minutes': 5,  # Wait 5 minutes after news
    },
    'low_volume': {
        'enabled': True,
        'threshold': 0.30,  # Block if volume < 30% of average
    },
    'new_candle_timing': {
        'enabled': True,
        'block_first_seconds': 5,  # Don't trade first 5 seconds of new candle
    },
    'chop_detection': {
        'enabled': True,
        'method': 'adx',  # Use ADX for chop detection
        'adx_threshold': 20,  # ADX < 20 indicates chop
    },
}

# ═══════════════════════════════════════════════════════════════════
# AI MOMENTUM ENGINE (OPTIONAL)
# ═══════════════════════════════════════════════════════════════════

AI_ENGINE = {
    'enabled': False,  # Disabled by default (no model available)
    'model_path': None,  # Path to AI model weights
    'min_score': 4,  # Minimum score of 4 required for trade
    'max_score': 10,  # Maximum possible score
    'features': [
        'price_momentum',
        'volume_profile',
        'trend_strength',
        'volatility_regime',
        'time_of_day',
    ],
}

# ═══════════════════════════════════════════════════════════════════
# BACKTEST & LIVE CONFIGURATION
# ═══════════════════════════════════════════════════════════════════

EXECUTION = {
    'mode': 'live',  # 'backtest' or 'live'
    'timeframe': '5m',  # 5-minute candles
    'candles_required': 100,  # Minimum candles needed for indicators
    'order_type': 'market',  # Market orders for entries
    'slippage_model': 'realistic',  # Account for slippage in backtest
}

# ═══════════════════════════════════════════════════════════════════
# BROKER ADAPTERS
# ═══════════════════════════════════════════════════════════════════

BROKERS = {
    'supported': ['coinbase', 'binance', 'alpaca'],
    'default': 'coinbase',
    'coinbase': {
        'enabled': True,
        'asset_classes': ['crypto'],
    },
    'binance': {
        'enabled': False,  # Placeholder
        'asset_classes': ['crypto', 'futures'],
    },
    'alpaca': {
        'enabled': False,  # Placeholder
        'asset_classes': ['stocks'],
    },
}

# ═══════════════════════════════════════════════════════════════════
# TRADING PAIRS (for live trading)
# ═══════════════════════════════════════════════════════════════════

TRADING_PAIRS = {
    'crypto': ['BTC-USD', 'ETH-USD', 'SOL-USD'],
    'scan_all_available': True,  # Scan all available pairs on exchange
}

# ═══════════════════════════════════════════════════════════════════
# RISK LIMITS
# ═══════════════════════════════════════════════════════════════════

RISK_LIMITS = {
    'max_daily_loss': 0.025,  # 2.5% max daily loss
    'max_exposure': 0.30,  # 30% max total exposure
    'max_positions': 5,  # Maximum concurrent positions
    'max_trades_per_day': 20,  # Maximum trades per day
}
