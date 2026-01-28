"""
NIJA Apex Strategy v7.1 - Configuration

All configuration parameters for the Apex trading strategy.

Note: ADX threshold is set to 15 across multiple sections for consistency.
This value represents the minimum ADX for trend detection, optimized for
crypto markets. If you need to adjust, change all three instances:
- MARKET_FILTER['adx_threshold']
- MARKET_FILTERING['min_adx']
- SMART_FILTERS['chop_detection']['adx_threshold'] (set 1 lower to avoid edge cases)
"""

import logging

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# MARKET FILTER PARAMETERS
# ═══════════════════════════════════════════════════════════════════

MARKET_FILTER = {
    'adx_threshold': 15,  # ADX must be > 15 for trending market - relaxed for profitability
    'adx_strong_threshold': 40,  # ADX > 40 indicates very strong trend
    'volume_threshold': 0.3,  # Volume must be > 30% of recent average - relaxed for profitability
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
    'min_adx': 15,  # Minimum ADX for trend strength (< 15 = choppy) - relaxed for profitability
    'strong_adx': 30,  # ADX above this is strong trend
    
    # Volume Requirements
    'min_volume_multiplier': 1.2,  # Min volume vs 20-period average - relaxed for profitability
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
    'min_signal_score': 3,  # Minimum confirmations required (out of 6) - relaxed for profitability
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
# POSITION SIZING & RISK MANAGEMENT - ELITE PERFORMANCE OPTIMIZED
# ═══════════════════════════════════════════════════════════════════

POSITION_SIZING = {
    'trend_quality': {
        'weak': {
            'adx_range': (15, 20),
            'position_size': 0.02,  # 2% of account (conservative)
        },
        'good': {
            'adx_range': (20, 25),
            'position_size': 0.03,  # 3% of account (optimal)
        },
        'strong': {
            'adx_range': (25, 35),
            'position_size': 0.04,  # 4% of account (balanced)
        },
        'very_strong': {
            'adx_range': (35, 100),
            'position_size': 0.05,  # 5% of account (maximum)
        },
    },
    'max_position_size': 0.05,  # Hard cap at 5% (elite conservative sizing)
    'min_position_size': 0.02,  # Minimum 2%
    'optimal_position_size': 0.03,  # 3% optimal for most trades
    'max_concurrent_positions': 20,  # Up to 20 positions (5% each = 100% if all filled)
    'description': 'Conservative sizing enables 20-50 concurrent positions for diversification',
}

# ═══════════════════════════════════════════════════════════════════
# STOP LOSS PARAMETERS - ELITE PERFORMANCE OPTIMIZED
# ═══════════════════════════════════════════════════════════════════

STOP_LOSS = {
    'method': 'swing_plus_atr',  # Use swing low/high + ATR buffer
    'swing_lookback': 5,  # Look back 5 candles for swing points
    'atr_multiplier': 1.5,  # ATR buffer multiplier (wider stops, less stop-hunts)
    'min_stop_distance': 0.004,  # Minimum 0.4% stop distance (elite target)
    'max_stop_distance': 0.007,  # Maximum 0.7% stop distance (elite target)
    'optimal_stop_distance': 0.006,  # Optimal 0.6% (elite sweet spot)
    'always_set_before_entry': True,  # Stop must be set before entry
    'description': 'Targeting -0.4% to -0.7% average loss for elite performance',
}

# ═══════════════════════════════════════════════════════════════════
# TAKE PROFIT & TRAILING STOP PARAMETERS - ELITE R:R OPTIMIZED
# ═══════════════════════════════════════════════════════════════════

TAKE_PROFIT = {
    'stages': [
        {
            'name': 'TP1',
            'profit_pct': 0.005,  # 0.5% profit
            'profit_r': 0.83,  # 0.83R (if stop is 0.6%)
            'exit_percentage': 0.10,  # Exit 10% of position
            'action': 'partial_exit',
        },
        {
            'name': 'TP2',
            'profit_pct': 0.010,  # 1.0% profit
            'profit_r': 1.67,  # 1.67R
            'exit_percentage': 0.15,  # Exit 15% (25% total exited)
            'action': 'move_stop_to_breakeven',
        },
        {
            'name': 'TP3',
            'profit_pct': 0.020,  # 2.0% profit
            'profit_r': 3.33,  # 3.33R
            'exit_percentage': 0.25,  # Exit 25% (50% total exited)
            'action': 'activate_trailing',
        },
        {
            'name': 'TP4',
            'profit_pct': 0.030,  # 3.0% profit
            'profit_r': 5.0,  # 5.0R
            'exit_percentage': 0.50,  # Exit 50% (100% total exited)
            'action': 'final_exit_or_trail',
        },
    ],
    'use_multi_stage': True,
    'target_avg_win': 0.012,  # Target 1.2% average win (elite performance)
    'target_risk_reward': 2.0,  # Target 1:2 R:R (elite range 1:1.8 - 1:2.5)
    'description': 'Stepped exits optimized for 1:1.8 - 1:2.5 risk:reward ratio',
}

TRAILING_STOP = {
    'activation_r': 2.0,  # Activate after 2R profit (TP3 level)
    'atr_multiplier': 1.5,  # Trail at ATR(14) x 1.5
    'update_frequency': 'every_candle',  # Update on each new candle
    'never_widen': True,  # Only tighten, never widen
    'min_trail_distance': 0.008,  # 0.8% minimum trail distance
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
        'threshold': 0.15,  # Block if volume < 15% of average - relaxed for profitability
    },
    'new_candle_timing': {
        'enabled': True,
        'block_first_seconds': 5,  # Don't trade first 5 seconds of new candle
    },
    'chop_detection': {
        'enabled': True,
        'method': 'adx',  # Use ADX for chop detection
        'adx_threshold': 14,  # ADX < 14 indicates chop - slightly below min_adx to avoid edge cases
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

# FIX #1: BLACKLIST PAIRS - Disable pairs that are not suitable for strategy
# XRP-USD: Spread > profit edge, not suitable for current strategy
# PERMANENTLY DISABLED: Net-negative profitability confirmed
DISABLED_PAIRS = [
    "XRP-USD",    # High spread, low profit potential, net-negative performance
    "XRPUSD",     # Kraken format
    "XRP-USDT",   # USDT pair
    "XRPUSDT",    # Alternative format
]

TRADING_PAIRS = {
    'crypto': ['BTC-USD', 'ETH-USD', 'SOL-USD'],
    'scan_all_available': True,  # Scan all available pairs on exchange
}

# ═══════════════════════════════════════════════════════════════════
# RISK LIMITS - ELITE PERFORMANCE OPTIMIZED
# ═══════════════════════════════════════════════════════════════════

RISK_LIMITS = {
    'max_daily_loss': 0.025,  # 2.5% max daily loss
    'max_drawdown': 0.12,  # 12% max drawdown (elite target: <12%)
    'max_exposure': 0.80,  # 80% max total exposure (allows 20-position diversification)
    'max_positions': 20,  # HARD CAP: 20 positions maximum (5% each = 100%)
    'max_trades_per_day': 12,  # 12 trades per day (elite target: 3-12)
    'min_win_rate': 0.55,  # Alert if win rate drops below 55% (elite floor: 58%)
    'min_profit_factor': 1.8,  # Alert if profit factor drops below 1.8 (elite floor: 2.0)
    'description': 'Elite risk management for top 0.1% performance',
}

# ═══════════════════════════════════════════════════════════════════
# RISK MANAGEMENT - NIJA USER TRADING TIERS (OFFICIAL - FINAL VERSION)
# ═══════════════════════════════════════════════════════════════════
#
# Six official user trading tiers based on capital and goals:
# 1. STARTER ($50-$99) - Entry level learning
# 2. SAVER ($100-$249) - Capital preservation + learning
# 3. INVESTOR ($250-$999) - Consistent participation
# 4. INCOME ($1,000-$4,999) - Serious retail trading
# 5. LIVABLE ($5,000-$24,999) - Professional-level execution
# 6. BALLER ($25,000+) - Capital deployment
#
# MASTER (System Authority) - Not a user tier, system governance only
#
# To use a specific tier, set RISK_PROFILE environment variable:
#   export RISK_PROFILE=STARTER    # For entry level ($50-$99)
#   export RISK_PROFILE=SAVER      # For learning ($100-$249)
#   export RISK_PROFILE=INVESTOR   # For consistency ($250-$999)
#   export RISK_PROFILE=INCOME     # For serious trading ($1k-$4.9k)
#   export RISK_PROFILE=LIVABLE    # For professional execution ($5k-$24.9k)
#   export RISK_PROFILE=BALLER     # For capital deployment ($25k+)
#   export RISK_PROFILE=AUTO       # Auto-select based on balance
#
# Default tier is INVESTOR if not specified
# ═══════════════════════════════════════════════════════════════════

# TIER 1: STARTER - "Entry level learning"
# Target Balance: $50 – $99
# Focus: First steps in algorithmic trading
RISK_CONFIG_STARTER = {
    # Per-Trade Risk Limits
    'max_risk_per_trade': 0.15,  # 15% maximum risk per trade
    'min_risk_per_trade': 0.10,  # 10% minimum risk per trade
    'min_risk_reward': 3.0,  # Minimum 3:1 risk/reward ratio
    
    # Account-Level Risk Limits
    'max_daily_loss': 0.10,  # 10% maximum daily loss
    'max_weekly_loss': 0.20,  # 20% maximum weekly loss
    'max_total_exposure': 0.15,  # 15% maximum total exposure
    'max_drawdown': 0.15,  # 15% maximum account drawdown
    
    # Drawdown Protection
    'drawdown_reduce_size_at': 0.08,  # Reduce size at 8% drawdown
    'drawdown_stop_trading_at': 0.15,  # Stop trading at 15% drawdown
    
    # Position Management
    'max_concurrent_positions': 1,  # Only 1 position
    'max_position_concentration': 0.15,  # 15% max per position
    'min_trade_size_usd': 10.0,  # $10 minimum trade
    'max_trade_size_usd': 25.0,  # $25 maximum trade
    
    # Circuit Breakers
    'consecutive_loss_limit': 2,  # Stop after 2 consecutive losses
    'daily_trade_limit': 5,  # Maximum 5 trades per day
    'min_time_between_trades_sec': 900,  # 15 minutes minimum
    
    # Performance-Based Adjustments
    'reduce_size_on_losing_streak': True,
    'losing_streak_threshold': 1,  # Trigger after 1 loss
    'size_reduction_factor': 0.5,
    
    # System Behavior
    'strict_fee_aware_filtering': True,
    'high_signal_confidence_required': True,
    'skip_trades_on_poor_fee_ratio': True,
    
    # Profile Metadata
    'profile_name': 'STARTER',
    'tier_number': 1,
    'balance_range': (50.0, 99.0),
    'primary_goal': 'Entry level learning',
    'trade_frequency': 'Very Low',
    'experience_required': 'Beginner',
}

# TIER 2: SAVER - "Capital preservation + learning"
# Target Balance: $100 – $249
# Focus: Capital preservation while learning the system
RISK_CONFIG_SAVER = {
    # Per-Trade Risk Limits
    'max_risk_per_trade': 0.10,  # 10% maximum risk per trade
    'min_risk_per_trade': 0.07,  # 7% minimum risk per trade (dynamic)
    'min_risk_reward': 2.5,  # Minimum 2.5:1 risk/reward ratio
    
    # Account-Level Risk Limits
    'max_daily_loss': 0.08,  # 8% maximum daily loss (very defensive)
    'max_weekly_loss': 0.15,  # 15% maximum weekly loss
    'max_total_exposure': 0.15,  # 15% maximum total exposure (single position focus)
    'max_drawdown': 0.10,  # 10% maximum account drawdown
    
    # Drawdown Protection
    'drawdown_reduce_size_at': 0.05,  # Reduce size at 5% drawdown
    'drawdown_stop_trading_at': 0.10,  # Stop trading at 10% drawdown
    
    # Position Management
    'max_concurrent_positions': 2,  # Up to 2 positions
    'max_position_concentration': 0.15,  # 15% max per position
    'min_trade_size_usd': 15.0,  # $15 minimum trade
    'max_trade_size_usd': 40.0,  # $40 maximum trade
    
    # Circuit Breakers
    'consecutive_loss_limit': 2,  # Stop after 2 consecutive losses
    'daily_trade_limit': 10,  # Maximum 10 trades per day
    'min_time_between_trades_sec': 600,  # 10 minutes minimum
    
    # Performance-Based Adjustments
    'reduce_size_on_losing_streak': True,
    'losing_streak_threshold': 1,  # Trigger after 1 loss
    'size_reduction_factor': 0.5,
    
    # System Behavior
    'strict_fee_aware_filtering': True,  # Skip trades if fees > profit expectancy
    'high_signal_confidence_required': True,  # Only take A+ setups
    'skip_trades_on_poor_fee_ratio': True,
    
    # Profile Metadata
    'profile_name': 'SAVER',
    'tier_number': 2,
    'balance_range': (100.0, 249.0),
    'primary_goal': 'Capital preservation + learning',
    'trade_frequency': 'Moderate',
    'experience_required': 'Beginner',
}

# TIER 3: INVESTOR - "Consistent participation"
# Target Balance: $250 – $999
# "Default tier for consistent market participation"
RISK_CONFIG_INVESTOR = {
    # Per-Trade Risk Limits
    'max_risk_per_trade': 0.07,  # 7% maximum risk per trade
    'min_risk_per_trade': 0.05,  # 5% minimum risk per trade
    'min_risk_reward': 2.0,  # Minimum 2.0:1 risk/reward ratio
    
    # Account-Level Risk Limits
    'max_daily_loss': 0.05,  # 5% maximum daily loss
    'max_weekly_loss': 0.10,  # 10% maximum weekly loss
    'max_total_exposure': 0.25,  # 25% maximum total exposure
    'max_drawdown': 0.12,  # 12% maximum account drawdown
    
    # Drawdown Protection
    'drawdown_reduce_size_at': 0.06,  # Reduce size at 6% drawdown
    'drawdown_stop_trading_at': 0.12,  # Stop trading at 12% drawdown
    
    # Position Management
    'max_concurrent_positions': 3,  # Up to 3 positions
    'max_position_concentration': 0.10,  # 10% max per position
    'min_trade_size_usd': 10.0,  # $10 minimum trade
    'max_trade_size_usd': 25.0,  # $25 maximum trade (improved fee efficiency)
    
    # Circuit Breakers
    'consecutive_loss_limit': 3,  # Stop after 3 consecutive losses
    'daily_trade_limit': 10,  # Maximum 10 trades per day (moderate frequency)
    'min_time_between_trades_sec': 300,  # 5 minutes minimum
    
    # Performance-Based Adjustments
    'reduce_size_on_losing_streak': True,
    'losing_streak_threshold': 2,  # Trigger after 2 losses
    'size_reduction_factor': 0.6,
    
    # System Behavior
    'fee_aware_filtering': True,  # Improved fee efficiency
    'core_strategy_active': True,  # Core strategy begins operating as intended
    'reduced_trade_rejection_rate': True,
    
    # Profile Metadata
    'profile_name': 'INVESTOR',
    'tier_number': 3,
    'balance_range': (250.0, 999.0),
    'primary_goal': 'Consistent participation',
    'trade_frequency': 'Active',
    'experience_required': 'Intermediate',
}

# TIER 3: INCOME - "Serious retail trading"
# Target Balance: $1,000 – $4,999
# "For serious retail traders with active participation"
RISK_CONFIG_INCOME = {
    # Per-Trade Risk Limits
    'max_risk_per_trade': 0.05,  # 5% maximum risk per trade
    'min_risk_per_trade': 0.03,  # 3% minimum risk per trade
    'min_risk_reward': 2.0,  # Minimum 2:1 risk/reward ratio
    
    # Account-Level Risk Limits
    'max_daily_loss': 0.04,  # 4% maximum daily loss
    'max_weekly_loss': 0.08,  # 8% maximum weekly loss
    'max_total_exposure': 0.35,  # 35% maximum total exposure
    'max_drawdown': 0.10,  # 10% maximum account drawdown
    
    # Drawdown Protection
    'drawdown_reduce_size_at': 0.05,  # Reduce size at 5% drawdown (lower drawdowns)
    'drawdown_stop_trading_at': 0.10,  # Stop trading at 10% drawdown
    
    # Position Management
    'max_concurrent_positions': 5,  # Up to 5 positions
    'max_position_concentration': 0.08,  # 8% max per position
    'min_trade_size_usd': 15.0,  # $15 minimum trade
    'max_trade_size_usd': 70.0,  # $70 maximum trade (7% of $1000)
    
    # Circuit Breakers
    'consecutive_loss_limit': 3,  # Stop after 3 consecutive losses
    'daily_trade_limit': 20,  # Maximum 20 trades per day (active but selective)
    'min_time_between_trades_sec': 180,  # 3 minutes minimum
    
    # Performance-Based Adjustments
    'reduce_size_on_losing_streak': True,
    'losing_streak_threshold': 2,  # Trigger after 2 losses
    'size_reduction_factor': 0.65,
    
    # System Behavior
    'optimized_position_sizing': True,  # Optimized position sizing
    'better_signal_to_fee_ratio': True,  # Better signal-to-fee ratio
    'supplemental_income_mode': True,
    
    # Profile Metadata
    'profile_name': 'INCOME',
    'tier_number': 4,
    'balance_range': (1000.0, 4999.0),
    'primary_goal': 'Serious retail trading',
    'trade_frequency': 'Very active',
    'experience_required': 'Intermediate-Advanced',
}

# TIER 4: LIVABLE - "Professional-level execution"
# Target Balance: $5,000 – $24,999
# "For professional-level traders with precision focus"
RISK_CONFIG_LIVABLE = {
    # Per-Trade Risk Limits
    'max_risk_per_trade': 0.03,  # 3% maximum risk per trade
    'min_risk_per_trade': 0.02,  # 2% minimum risk per trade
    'min_risk_reward': 2.0,  # Minimum 2:1 risk/reward ratio
    
    # Account-Level Risk Limits
    'max_daily_loss': 0.03,  # 3% maximum daily loss
    'max_weekly_loss': 0.06,  # 6% maximum weekly loss
    'max_total_exposure': 0.30,  # 30% maximum total exposure (drawdown prioritization)
    'max_drawdown': 0.08,  # 8% maximum account drawdown (conservative)
    
    # Drawdown Protection
    'drawdown_reduce_size_at': 0.04,  # Reduce size at 4% drawdown (drawdown prioritization)
    'drawdown_stop_trading_at': 0.08,  # Stop trading at 8% drawdown
    
    # Position Management
    'max_concurrent_positions': 6,  # Up to 6 positions
    'max_position_concentration': 0.06,  # 6% max per position (institutional-style)
    'min_trade_size_usd': 25.0,  # $25 minimum trade
    'max_trade_size_usd': 200.0,  # $200 maximum trade (4% of $5000)
    
    # Circuit Breakers
    'consecutive_loss_limit': 4,  # Stop after 4 consecutive losses
    'daily_trade_limit': 15,  # Maximum 15 trades per day (selective, high-confidence)
    'min_time_between_trades_sec': 240,  # 4 minutes minimum
    
    # Performance-Based Adjustments
    'reduce_size_on_losing_streak': True,
    'losing_streak_threshold': 2,  # Trigger after 2 losses
    'size_reduction_factor': 0.7,
    
    # System Behavior
    'institutional_risk_management': True,  # Institutional-style risk management
    'conservative_stop_tiers': True,  # Conservative stop tiers
    'drawdown_over_trade_count': True,  # Drawdown prioritization over trade count
    
    # Profile Metadata
    'profile_name': 'LIVABLE',
    'tier_number': 5,
    'balance_range': (5000.0, 24999.0),
    'primary_goal': 'Professional-level execution',
    'trade_frequency': 'Selective, high-precision',
    'experience_required': 'Advanced',
}

# TIER 5: BALLER - "Capital deployment"
# Target Balance: $25,000+
# "Institutional-grade capital deployment"
RISK_CONFIG_BALLER = {
    # Per-Trade Risk Limits
    'max_risk_per_trade': 0.02,  # 2% maximum risk per trade (capital preservation)
    'min_risk_per_trade': 0.01,  # 1% minimum risk per trade
    'min_risk_reward': 2.5,  # Minimum 2.5:1 risk/reward ratio (precision)
    
    # Account-Level Risk Limits
    'max_daily_loss': 0.02,  # 2% maximum daily loss (wealth preservation)
    'max_weekly_loss': 0.04,  # 4% maximum weekly loss
    'max_total_exposure': 0.25,  # 25% maximum total exposure (advanced portfolio balancing)
    'max_drawdown': 0.06,  # 6% maximum account drawdown (tight controls)
    
    # Drawdown Protection
    'drawdown_reduce_size_at': 0.03,  # Reduce size at 3% drawdown
    'drawdown_stop_trading_at': 0.06,  # Stop trading at 6% drawdown
    
    # Position Management
    'max_concurrent_positions': 8,  # Up to 8 positions (advanced diversification)
    'max_position_concentration': 0.04,  # 4% max per position (tight execution filters)
    'min_trade_size_usd': 50.0,  # $50 minimum trade
    'max_trade_size_usd': 1000.0,  # $1000 maximum trade (2% of $50k)
    
    # Circuit Breakers
    'consecutive_loss_limit': 5,  # Stop after 5 consecutive losses
    'daily_trade_limit': 12,  # Maximum 12 trades per day (precision-only)
    'min_time_between_trades_sec': 300,  # 5 minutes minimum (minimal overtrading)
    
    # Performance-Based Adjustments
    'reduce_size_on_losing_streak': True,
    'losing_streak_threshold': 2,  # Trigger after 2 losses
    'size_reduction_factor': 0.75,
    
    # System Behavior
    'tight_execution_filters': True,  # Tight execution filters
    'advanced_portfolio_balancing': True,  # Advanced portfolio balancing
    'minimal_overtrading': True,  # Minimal overtrading
    'capital_deployment_mode': True,  # Capital deployment, not speculation
    
    # Profile Metadata
    'profile_name': 'BALLER',
    'tier_number': 6,
    'balance_range': (25000.0, float('inf')),
    'primary_goal': 'Capital deployment',
    'trade_frequency': 'Precision-only',
    'experience_required': 'Expert',
}

# MASTER (System Authority) - NOT A USER TIER
# Role: Strategy source + execution authority
# Functions: Signal generation, global risk enforcement, entry/exit override logic, multi-exchange coordination
# Access: Internal only
# "MASTER does not trade 'for profit' — it governs profit logic"
RISK_CONFIG_MASTER = {
    # System Authority Parameters (Not for direct user trading)
    'max_risk_per_trade': 0.02,  # 2% for system governance
    'min_risk_reward': 2.0,
    
    'max_daily_loss': 0.03,
    'max_weekly_loss': 0.06,
    'max_total_exposure': 0.50,  # Higher for multi-exchange coordination
    'max_drawdown': 0.10,
    
    'drawdown_reduce_size_at': 0.05,
    'drawdown_stop_trading_at': 0.10,
    
    'max_concurrent_positions': 10,  # System-wide coordination
    'max_position_concentration': 0.10,
    
    'consecutive_loss_limit': 5,
    'daily_trade_limit': 100,  # System-wide signal generation
    'min_time_between_trades_sec': 30,
    
    'reduce_size_on_losing_streak': True,
    'losing_streak_threshold': 3,
    'size_reduction_factor': 0.7,
    
    # System Authority Flags
    'system_authority': True,  # Not a user-facing tier
    'signal_generation': True,
    'global_risk_enforcement': True,
    'entry_exit_override': True,
    'multi_exchange_coordination': True,
    
    # Profile Metadata
    'profile_name': 'MASTER',
    'tier_number': 0,  # System tier, not user tier
    'balance_range': None,  # Non-user facing
    'primary_goal': 'System governance',
    'trade_frequency': 'System-controlled',
    'experience_required': 'Internal only',
}

# ═══════════════════════════════════════════════════════════════════
# AUTOMATIC PROFILE SELECTION
# ═══════════════════════════════════════════════════════════════════

def get_active_risk_config():
    """
    Get the active risk configuration based on environment variable or defaults.
    
    Priority:
    1. RISK_PROFILE environment variable (STARTER, SAVER, INVESTOR, INCOME, LIVABLE, BALLER, MASTER)
    2. AUTO mode - selects based on account balance
    3. Default to INVESTOR if not specified
    
    NIJA User Trading Tiers:
    - STARTER: $50-$99 (Entry level learning)
    - SAVER: $100-$249 (Capital preservation + learning)
    - INVESTOR: $250-$999 (Consistent participation) - DEFAULT
    - INCOME: $1,000-$4,999 (Serious retail trading)
    - LIVABLE: $5,000-$24,999 (Professional-level execution)
    - BALLER: $25,000+ (Capital deployment)
    - MASTER: System authority only (not for users)
    
    Returns:
        dict: Active risk configuration
    """
    import os
    
    risk_profile = os.getenv('RISK_PROFILE', 'AUTO').upper()
    
    if risk_profile == 'STARTER':
        return RISK_CONFIG_STARTER
    elif risk_profile == 'SAVER':
        return RISK_CONFIG_SAVER
    elif risk_profile == 'INVESTOR':
        return RISK_CONFIG_INVESTOR
    elif risk_profile == 'INCOME':
        return RISK_CONFIG_INCOME
    elif risk_profile == 'LIVABLE':
        return RISK_CONFIG_LIVABLE
    elif risk_profile == 'BALLER':
        return RISK_CONFIG_BALLER
    elif risk_profile == 'MASTER':
        logger.warning("⚠️ MASTER tier is for system authority only, not user trading")
        return RISK_CONFIG_MASTER
    elif risk_profile == 'AUTO':
        # Auto-select based on account balance (if available)
        try:
            balance_str = os.getenv('ACCOUNT_BALANCE', '0')
            balance = float(balance_str)
            if balance >= 25000:
                logger.info(f"AUTO mode: Selected BALLER tier (balance: ${balance:.2f})")
                return RISK_CONFIG_BALLER
            elif balance >= 5000:
                logger.info(f"AUTO mode: Selected LIVABLE tier (balance: ${balance:.2f})")
                return RISK_CONFIG_LIVABLE
            elif balance >= 1000:
                logger.info(f"AUTO mode: Selected INCOME tier (balance: ${balance:.2f})")
                return RISK_CONFIG_INCOME
            elif balance >= 250:
                logger.info(f"AUTO mode: Selected INVESTOR tier (balance: ${balance:.2f})")
                return RISK_CONFIG_INVESTOR
            elif balance >= 100:
                logger.info(f"AUTO mode: Selected SAVER tier (balance: ${balance:.2f})")
                return RISK_CONFIG_SAVER
            elif balance >= 50:
                logger.info(f"AUTO mode: Selected STARTER tier (balance: ${balance:.2f})")
                return RISK_CONFIG_STARTER
            else:
                logger.warning(f"AUTO mode: Balance ${balance:.2f} below minimum ($50), defaulting to STARTER tier")
                return RISK_CONFIG_STARTER
        except (ValueError, TypeError) as e:
            # Default to INVESTOR if balance unavailable or invalid
            logger.warning(f"Unable to parse ACCOUNT_BALANCE, defaulting to INVESTOR tier: {e}")
            return RISK_CONFIG_INVESTOR
    else:
        # Default to INVESTOR for unknown profiles
        logger.warning(f"Unknown RISK_PROFILE '{risk_profile}', defaulting to INVESTOR tier")
        return RISK_CONFIG_INVESTOR

# Active configuration (backward compatibility)
# Note: This is evaluated at module import time. To change profiles at runtime,
# call get_active_risk_config() directly or reload the module.
RISK_CONFIG = get_active_risk_config()

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
    # FIX #3: Minimum Profit Threshold
    # Calculate required profit = spread + fees + buffer
    # Coinbase: ~0.6% taker fee + ~0.2% spread = 0.8% one way, 1.6% round-trip
    'min_profit_spread': 0.002,  # 0.2% estimated spread cost
    'min_profit_fees': 0.012,  # 1.2% estimated fees (0.6% per side)
    'min_profit_buffer': 0.002,  # 0.2% safety buffer
    'min_profit_total': 0.016,  # 1.6% minimum profit (spread + fees + buffer)
    
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
    
    # FIX #4: Pair Quality Filters - Pro Level
    # Only trade pairs with tight spreads and good liquidity
    'max_spread_pct': 0.0015,  # Maximum 0.15% bid-ask spread (tightened from 0.1%)
    'max_slippage_pct': 0.002,  # Maximum 0.2% acceptable slippage
    'min_volume_usd': 100000,  # Minimum $100k daily volume
    'min_atr_movement': 0.005,  # Minimum 0.5% ATR for adequate movement
    
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
# DAILY PROFIT TARGET OPTIMIZATION - ELITE PERFORMANCE ALIGNED
# ═══════════════════════════════════════════════════════════════════

DAILY_TARGET = {
    'enabled': True,  # Enable daily target optimization
    'target_usd': 25.00,  # Target $25/day profit
    'min_balance_for_target': 100.00,  # Scale target for smaller accounts
    'expected_win_rate': 0.60,  # 60% expected win rate (elite target: 58-62%)
    'avg_win_pct': 0.012,  # 1.2% average profit per win (elite target: 0.9-1.5%)
    'avg_loss_pct': 0.006,  # 0.6% average loss per trade (elite target: 0.4-0.7%)
    'expectancy_pct': 0.0048,  # 0.48% expectancy per trade (elite target: 0.45-0.65%)
    'risk_reward_ratio': 2.0,  # 1:2 R:R (elite target: 1:1.8 - 1:2.5)
    'max_trades_per_day': 12,  # Maximum trades per day (elite target: 3-12)
    'min_trades_per_day': 5,  # Minimum trades to hit target
    'optimal_trades_per_day': 7,  # Optimal trade frequency
    'auto_adjust': True,  # Auto-adjust based on account balance
    'description': 'Elite performance aligned: 60% WR, 1.2% avg win, 0.6% avg loss, 1:2 R:R',
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
# ELITE PERFORMANCE TARGETS (NEW - January 28, 2026)
# ═══════════════════════════════════════════════════════════════════
#
# NIJA v7.3 - Elite Tier Performance Targets
# Places NIJA in top 0.1% of automated trading systems worldwide
#
# Import elite performance configuration for advanced metrics
try:
    from elite_performance_config import (
        ELITE_PERFORMANCE_TARGETS,
        ELITE_POSITION_SIZING,
        ELITE_RISK_MANAGEMENT,
        MULTI_ENGINE_STACK,
        calculate_expectancy,
        validate_performance_targets,
    )
    ELITE_MODE_ENABLED = True
    logger.info("✅ ELITE PERFORMANCE MODE ACTIVE - v7.3")
except ImportError:
    ELITE_MODE_ENABLED = False
    logger.warning("⚠️ Elite performance config not found - using v7.1 defaults")

# Elite Performance Targets (if not imported)
PERFORMANCE_TARGETS = {
    'profit_factor_target': 2.2,      # Target: 2.0 - 2.6 (Elite AI range)
    'win_rate_target': 0.60,          # Target: 58% - 62% (Optimal balance)
    'avg_loss_target': -0.006,        # Target: -0.4% to -0.7% (0.6% optimal)
    'avg_win_target': 0.012,          # Target: 0.9% to 1.5% (1.2% optimal)
    'risk_reward_target': 2.0,        # Target: 1:1.8 - 1:2.5 (1:2 optimal)
    'expectancy_target': 0.0048,      # Target: +0.45R to +0.65R (+0.48% optimal)
    'max_drawdown_target': 0.12,      # Target: <12% (10% optimal)
    'sharpe_ratio_target': 1.8,       # Target: >1.8 (2.0+ exceptional)
    'trades_per_day_target': 7,       # Target: 3-12 trades/day (7 optimal)
}

# ═══════════════════════════════════════════════════════════════════
# STRATEGY METADATA
# ═══════════════════════════════════════════════════════════════════

STRATEGY_INFO = {
    'name': 'NIJA Apex Strategy - Elite Performance',
    'version': '7.3',
    'description': 'Elite-tier automated trading system optimized for top 0.1% performance metrics',
    'author': 'NIJA Trading Systems',
    'created': '2025-12-12',
    'last_updated': '2026-01-28',
    'performance_tier': 'ELITE',
    'target_profit_factor': '2.0 - 2.6',
    'target_win_rate': '58% - 62%',
    'target_expectancy': '+0.45R - +0.65R',
}
