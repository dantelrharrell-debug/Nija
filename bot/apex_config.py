"""
NIJA Apex Strategy v7.1 - Configuration

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
# MARKET STATE FILTERING
# ═══════════════════════════════════════════════════════════════════

MARKET_FILTERING = {
    # ADX (Average Directional Index) - Trend Strength
    'min_adx': 20,  # Minimum ADX for trend strength (< 20 = choppy)
    'strong_adx': 30,  # ADX above this is strong trend
    
    # Volume Requirements
    'min_volume_multiplier': 1.5,  # Min volume vs 20-period average
    'strong_volume_multiplier': 2.0,  # Strong volume confirmation
    
    # ATR (Average True Range) - Volatility
    'min_atr_pct': 0.001,  # Minimum volatility (0.1% of price)
    'max_atr_pct': 0.05,  # Maximum volatility (5% of price)
    'optimal_atr_pct': 0.015,  # Optimal volatility range (1.5%)
}

# ═══════════════════════════════════════════════════════════════════
# ENTRY REQUIREMENTS
# ═══════════════════════════════════════════════════════════════════

ENTRY_CONFIG = {
    # Signal Scoring (6 possible confirmations)
    'min_signal_score': 4,  # Minimum confirmations required (out of 6)
    'a_plus_signal_score': 6,  # Perfect setup score
    
    # Required Conditions
    'require_ema_alignment': True,  # Must have EMA9 > EMA21 > EMA50 (or reverse)
    'require_vwap_alignment': True,  # Must have price above/below VWAP
    'require_adx_minimum': True,  # Must meet minimum ADX threshold
    
    # Indicator Periods
    'rsi_period': 14,
    'ema_fast': 9,
    'ema_medium': 21,
    'ema_slow': 50,
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
            'profit_r': 0.5,  # 0.5R (quick scalp - 1% profit)
            'exit_percentage': 0.50,  # Exit 50% of position
            'action': 'move_stop_to_breakeven',
        },
        {
            'name': 'TP2',
            'profit_r': 1.0,  # 1R (2% profit)
            'exit_percentage': 0.30,  # Exit another 30% (80% total)
            'action': 'activate_trailing',
        },
        {
            'name': 'TP3',
            'profit_r': 1.5,  # 1.5R (3% profit)
            'exit_percentage': 0.20,  # Exit remaining 20% (100% total)
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
    'min_candles_required': 100,  # Minimum candles needed for indicators
    'order_type': 'market',  # Market orders for entries
    'slippage_model': 'realistic',  # Account for slippage in backtest
}

# ═══════════════════════════════════════════════════════════════════
# BROKER ADAPTERS
# ═══════════════════════════════════════════════════════════════════

BROKERS = {
    'supported': ['coinbase', 'binance', 'alpaca', 'okx'],
    'default': 'coinbase',
    'coinbase': {
        'enabled': True,
        'asset_classes': ['crypto'],
    },
    'binance': {
        'enabled': False,  # Placeholder
        'asset_classes': ['crypto', 'futures'],
    },
    'okx': {
        'enabled': True,  # ✅ Ready to trade - just add credentials to .env
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
    'max_positions': 8,  # HARD CAP: 8 positions maximum (enforced at startup and per trade)
    'max_trades_per_day': 30,  # 30 trades per day (more active)
}

# ═══════════════════════════════════════════════════════════════════
# RISK MANAGEMENT
# ═══════════════════════════════════════════════════════════════════

RISK_CONFIG = {
    # Per-Trade Risk Limits
    'max_risk_per_trade': 0.02,  # 2% maximum risk per trade
    'min_risk_reward': 2.0,  # Minimum 2:1 risk/reward ratio
    
    # Account-Level Risk Limits
    'max_daily_loss': 0.025,  # 2.5% maximum daily loss
    'max_weekly_loss': 0.05,  # 5% maximum weekly loss
    'max_total_exposure': 0.30,  # 30% maximum total exposure
    'max_drawdown': 0.10,  # 10% maximum account drawdown
    
    # Drawdown Protection
    'drawdown_reduce_size_at': 0.05,  # Reduce size at 5% drawdown
    'drawdown_stop_trading_at': 0.10,  # Stop trading at 10% drawdown
}

# ═══════════════════════════════════════════════════════════════════
# POSITION SIZING
# ═══════════════════════════════════════════════════════════════════

POSITION_SIZING = {
    # Base Position Sizes
    'base_position_size': 0.03,  # 3% base position size
    'min_position_size': 0.01,  # 1% minimum position
    'max_position_size': 0.10,  # 10% maximum position
    
    # ADX-Weighted Sizing
    'use_adx_weighting': True,
    'adx_weak_multiplier': 0.5,  # 0.5x size when ADX < 20
    'adx_moderate_multiplier': 1.0,  # 1.0x size when ADX 20-40
    'adx_strong_multiplier': 1.5,  # 1.5x size when ADX > 40
    
    # Signal Score Weighting
    'score_multipliers': {
        6: 1.2,  # A+ setup: 120% of base size
        5: 1.0,  # Strong setup: 100% of base size
        4: 0.8,  # Good setup: 80% of base size
        3: 0.6,  # Moderate setup: 60% of base size
        2: 0.4,  # Minimum setup: 40% of base size
    }
}

# ═══════════════════════════════════════════════════════════════════
# STOP-LOSS CONFIGURATION
# ═══════════════════════════════════════════════════════════════════

STOP_LOSS_CONFIG = {
    # ATR-Based Stops
    'atr_stop_multiplier': 1.5,  # Stop = 1.5x ATR below entry
    'min_stop_pct': 0.003,  # Minimum 0.3% stop-loss
    'max_stop_pct': 0.015,  # Maximum 1.5% stop-loss
    
    # Stop-Loss Adjustment
    'adjust_stop_on_tp1': True,  # Move stop to breakeven at TP1
    'breakeven_buffer_pct': 0.001,  # 0.1% buffer above breakeven
}

# ═══════════════════════════════════════════════════════════════════
# TAKE-PROFIT CONFIGURATION
# ═══════════════════════════════════════════════════════════════════

TAKE_PROFIT_CONFIG = {
    # Tiered Take-Profit Levels
    'tp1': {
        'pct': 0.008,  # +0.8% profit
        'exit_size': 0.50,  # Exit 50% of position
        'action': 'activate_trailing_stop'
    },
    'tp2': {
        'pct': 0.015,  # +1.5% profit
        'exit_size': 0.30,  # Exit 30% of position (80% total)
        'action': 'tighten_trailing_stop'
    },
    'tp3': {
        'pct': 0.025,  # +2.5% profit
        'exit_size': 0.20,  # Exit final 20%
        'action': 'let_runner_trail'
    },
    
    # Trailing Stop (activates after TP1)
    'initial_trail_pct': 0.005,  # 0.5% trailing distance
    'tight_trail_pct': 0.003,  # 0.3% tight trail (after TP2)
    'min_trail_pct': 0.002,  # 0.2% minimum trail
}

# ═══════════════════════════════════════════════════════════════════
# MARKET FILTERS
# ═══════════════════════════════════════════════════════════════════

FILTERS_CONFIG = {
    # Time-Based Filters
    'candle_timing_seconds': 5,  # Avoid first 5 seconds of new candle
    'news_cooldown_minutes': 3,  # No trades for 3 min after major news
    
    # Spread and Slippage
    'max_spread_pct': 0.001,  # Maximum 0.1% bid-ask spread
    'max_slippage_pct': 0.002,  # Maximum 0.2% acceptable slippage
    
    # Market Hours (for stocks/futures, not crypto)
    'trade_market_hours_only': False,  # Crypto trades 24/7
    'avoid_first_minutes': 0,  # Minutes to avoid after market open
    'avoid_last_minutes': 0,  # Minutes to avoid before market close
}

# ═══════════════════════════════════════════════════════════════════
# AI AND ADVANCED FEATURES
# ═══════════════════════════════════════════════════════════════════

AI_CONFIG = {
    # AI Momentum Scoring
    'use_ai_momentum': False,  # Not yet implemented
    'ai_model_path': None,  # Path to trained ML model
    
    # Regime Detection
    'use_regime_detection': True,  # Enable market regime detection
    'adapt_to_regime': True,  # Adjust parameters based on regime
    
    # Adaptive Signal Weighting
    'use_adaptive_weights': True,  # Adjust signal weights by regime
}

# ═══════════════════════════════════════════════════════════════════
# BROKER CONFIGURATION
# ═══════════════════════════════════════════════════════════════════

BROKER_CONFIG = {
    # Default Broker
    'default_broker': 'coinbase',  # 'coinbase', 'binance', 'alpaca', or 'okx'
    
    # Broker-Specific Settings
    'coinbase': {
        'use_advanced_trade': True,
        'default_product_type': 'SPOT',
    },
    'binance': {
        'use_testnet': False,
        'default_product_type': 'SPOT',  # or 'FUTURES'
    },
    'okx': {
        'use_testnet': False,
        'default_product_type': 'SPOT',  # or 'FUTURES'
    },
    'alpaca': {
        'use_paper': True,  # Paper trading by default
        'default_product_type': 'STOCK',  # or 'CRYPTO'
    },
    
    # Order Execution
    'order_type': 'market',  # 'market' or 'limit'
    'limit_order_offset_pct': 0.0005,  # 0.05% offset for limit orders
    'order_timeout_seconds': 30,  # Cancel order if not filled in 30s
}

# ═══════════════════════════════════════════════════════════════════
# TRADING PAIRS
# ═══════════════════════════════════════════════════════════════════

TRADING_PAIRS = {
    # Coinbase pairs
    'coinbase': [
        'BTC-USD',
        'ETH-USD',
        'SOL-USD',
    ],
    
    # Binance pairs (for future use)
    'binance': [
        'BTCUSDT',
        'ETHUSDT',
        'SOLUSDT',
    ],
    
    # Alpaca pairs (for future use)
    'alpaca': [
        'AAPL',
        'TSLA',
        'SPY',
    ],
}

# ═══════════════════════════════════════════════════════════════════
# EXECUTION SETTINGS
# ═══════════════════════════════════════════════════════════════════

EXECUTION_CONFIG = {
    # Scan Frequency
    'scan_interval_seconds': 300,  # Scan every 5 minutes (5m candles)
    'max_scans_per_hour': 12,  # Limit API calls
    
    # Trade Limits
    'max_trades_per_day': 30,  # 30 trades per day (more active)
    'max_trades_per_hour': 10,  # 10 per hour (faster trading)
    'min_time_between_trades': 30,  # 30 seconds between trades (was 2 min)
    
    # Position Limits
    'max_positions': 8,  # 8 positions maximum (consistent with MAX_POSITIONS_ALLOWED)
    'max_positions_per_symbol': 1,  # One position per symbol
}

# ═══════════════════════════════════════════════════════════════════
# LOGGING AND MONITORING
# ═══════════════════════════════════════════════════════════════════

LOGGING_CONFIG = {
    'log_level': 'INFO',  # 'DEBUG', 'INFO', 'WARNING', 'ERROR'
    'log_file': 'nija_apex.log',
    'log_max_bytes': 10 * 1024 * 1024,  # 10 MB
    'log_backup_count': 5,
    'log_to_console': True,
}

# ═══════════════════════════════════════════════════════════════════
# ENVIRONMENT VARIABLES (DO NOT HARDCODE SECRETS)
# ═══════════════════════════════════════════════════════════════════

ENV_VARS_REQUIRED = [
    # Broker API Keys (load from environment)
    'COINBASE_API_KEY',
    'COINBASE_API_SECRET',
    'COINBASE_PEM_CONTENT',
    
    # Optional: Other brokers
    # 'BINANCE_API_KEY',
    # 'BINANCE_API_SECRET',
    # 'ALPACA_API_KEY',
    # 'ALPACA_API_SECRET',
    
    # Operational
    'LIVE_MODE',  # 'true' or 'false'
]

# ═══════════════════════════════════════════════════════════════════
# DAILY PROFIT TARGET OPTIMIZATION (NEW - Dec 30, 2025)
# ═══════════════════════════════════════════════════════════════════

DAILY_TARGET = {
    'enabled': True,  # Enable daily target optimization
    'target_usd': 25.00,  # Target $25/day profit
    'min_balance_for_target': 100.00,  # Scale target for smaller accounts
    'expected_win_rate': 0.60,  # 60% expected win rate
    'avg_win_pct': 0.020,  # 2.0% average profit per win
    'avg_loss_pct': 0.010,  # 1.0% average loss per trade
    'max_trades_per_day': 20,  # Maximum trades per day
    'min_trades_per_day': 5,  # Minimum trades to hit target
    'auto_adjust': True,  # Auto-adjust based on account balance
}

# ═══════════════════════════════════════════════════════════════════
# MULTI-EXCHANGE CAPITAL ALLOCATION (NEW - Dec 30, 2025)
# ═══════════════════════════════════════════════════════════════════

MULTI_EXCHANGE = {
    'enabled': True,  # Enable multi-exchange trading
    'allocation_strategy': 'hybrid',  # 'equal_weight', 'fee_optimized', 'risk_balanced', 'hybrid'
    'min_exchange_allocation': 0.15,  # Minimum 15% per exchange
    'max_exchange_allocation': 0.50,  # Maximum 50% per exchange
    'rebalance_threshold': 0.10,  # Rebalance when drift > 10%
    'auto_rebalance': True,  # Automatically rebalance when needed
    
    # Default allocations (used if no connected exchanges)
    'default_allocations': {
        'coinbase': 0.40,  # 40% - Most reliable
        'okx': 0.30,       # 30% - Lowest fees
        'kraken': 0.30,    # 30% - Balanced
        'binance': 0.0,    # 0% - Not integrated yet
    },
    
    # Exchange priorities (higher = preferred)
    'exchange_priority': {
        'coinbase': 3,  # High priority (reliable, US-based)
        'kraken': 2,    # Medium priority
        'okx': 1,       # Lower priority (new integration)
        'binance': 0,   # Not active
    }
}

# ═══════════════════════════════════════════════════════════════════
# EXCHANGE-SPECIFIC RISK PROFILES (NEW - Dec 30, 2025)
# ═══════════════════════════════════════════════════════════════════

EXCHANGE_PROFILES = {
    'use_exchange_profiles': True,  # Use exchange-specific settings
    'auto_select_best': True,  # Auto-select best exchange for balance
    
    # Override settings per exchange (applied on top of base config)
    'coinbase': {
        'min_position_pct': 0.15,  # 15% minimum
        'max_position_pct': 0.30,  # 30% maximum
        'min_profit_target': 0.025,  # 2.5% minimum (high fees)
        'max_trades_per_day': 15,  # Quality over quantity
    },
    'okx': {
        'min_position_pct': 0.05,  # 5% minimum
        'max_position_pct': 0.20,  # 20% maximum
        'min_profit_target': 0.015,  # 1.5% minimum (low fees)
        'max_trades_per_day': 30,  # Higher frequency
    },
    'kraken': {
        'min_position_pct': 0.10,  # 10% minimum
        'max_position_pct': 0.25,  # 25% maximum
        'min_profit_target': 0.020,  # 2.0% minimum (medium fees)
        'max_trades_per_day': 20,  # Balanced frequency
    },
}

# ═══════════════════════════════════════════════════════════════════
# STRATEGY METADATA
# ═══════════════════════════════════════════════════════════════════

STRATEGY_INFO = {
    'name': 'NIJA Apex Strategy',
    'version': '7.1',
    'description': 'Production-ready trading system with strict filtering and dynamic risk management',
    'author': 'NIJA Trading Systems',
    'created': '2025-12-12',
    'last_updated': '2025-12-30',
}
