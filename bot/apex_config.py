"""
NIJA Apex Strategy v7.1 - Configuration File

Centralized configuration for all strategy parameters.
No API keys or secrets - use environment variables for credentials.
"""

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
    'default_broker': 'coinbase',  # 'coinbase', 'binance', or 'alpaca'
    
    # Broker-Specific Settings
    'coinbase': {
        'use_advanced_trade': True,
        'default_product_type': 'SPOT',
    },
    'binance': {
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
    'max_trades_per_day': 15,
    'max_trades_per_hour': 5,
    'min_time_between_trades': 120,  # 2 minutes between trades
    
    # Position Limits
    'max_positions': 5,  # Maximum concurrent positions
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
# STRATEGY METADATA
# ═══════════════════════════════════════════════════════════════════

STRATEGY_INFO = {
    'name': 'NIJA Apex Strategy',
    'version': '7.1',
    'description': 'Production-ready trading system with strict filtering and dynamic risk management',
    'author': 'NIJA Trading Systems',
    'created': '2025-12-12',
    'last_updated': '2025-12-12',
}
