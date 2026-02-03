"""
NIJA Safe Small-Account Preset Configuration
============================================

Turnkey preset for $20-$100 accounts with:
- Full copy trading support
- Minimal API risk
- Controlled drawdown protection
- Conservative position sizing
- Fee-optimized trading

Perfect for:
- New traders learning the system
- Small account copy trading
- Risk-averse capital preservation
- Testing the bot with minimal capital

Author: NIJA Trading Systems
Version: 1.0
Date: January 20, 2026
"""

# ============================================================================
# ACCOUNT SIZE PARAMETERS
# ============================================================================

ACCOUNT_SIZE = {
    'min_balance': 20.00,  # Minimum $20 to start
    'max_balance': 100.00,  # Optimized for up to $100
    'recommended_starting': 50.00,  # $50 sweet spot
    'emergency_stop_balance': 15.00,  # Stop trading below $15
}

# ============================================================================
# RISK MANAGEMENT - ULTRA CONSERVATIVE
# ============================================================================

RISK_LIMITS = {
    # Per-Trade Limits (very tight for safety)
    'max_risk_per_trade_pct': 0.005,  # 0.5% max risk per trade
    'max_position_size_pct': 0.05,  # 5% max position size
    'min_position_size_pct': 0.02,  # 2% min position size
    'min_position_size_usd': 5.00,  # $5 minimum per trade

    # Account-Level Limits
    'max_daily_loss_pct': 0.02,  # 2% max daily loss
    'max_weekly_loss_pct': 0.04,  # 4% max weekly loss
    'max_total_exposure_pct': 0.15,  # 15% max total exposure
    'max_drawdown_pct': 0.08,  # 8% max drawdown before stopping

    # Position Limits
    'max_concurrent_positions': 2,  # Only 2 positions max
    'max_positions_per_symbol': 1,  # One per symbol

    # Trade Frequency Limits
    'max_trades_per_day': 8,  # Maximum 8 trades per day
    'max_trades_per_hour': 3,  # Maximum 3 per hour
    'min_time_between_trades_seconds': 300,  # 5 minutes between trades
}

# ============================================================================
# POSITION SIZING - CONSERVATIVE
# ============================================================================

POSITION_SIZING = {
    # Base sizing (very small)
    'base_position_pct': 0.03,  # 3% base position
    'max_position_pct': 0.05,  # 5% maximum
    'min_position_pct': 0.02,  # 2% minimum

    # Signal-based adjustments (conservative)
    'signal_multipliers': {
        6: 1.0,  # Perfect signal: 3% (base)
        5: 0.9,  # Strong signal: 2.7%
        4: 0.8,  # Good signal: 2.4%
        3: None,  # Skip trade (signal quality too low for small account safety)
    },

    # Balance-based adjustments
    'balance_tiers': {
        'under_30': 0.02,  # $20-30: 2% positions
        'under_50': 0.03,  # $30-50: 3% positions
        'under_75': 0.04,  # $50-75: 4% positions
        'over_75': 0.05,   # $75-100: 5% positions
    },

    # Never exceed these limits
    'absolute_max_position_usd': 10.00,  # Never more than $10 per trade
    'absolute_min_position_usd': 5.00,   # Never less than $5 (fee efficiency)
}

# ============================================================================
# STOP-LOSS CONFIGURATION - TIGHT STOPS
# ============================================================================

STOP_LOSS = {
    # Stop-loss percentages (very tight)
    'default_stop_pct': 0.005,  # 0.5% default stop
    'min_stop_pct': 0.003,  # 0.3% minimum
    'max_stop_pct': 0.007,  # 0.7% maximum

    # Stop-loss type
    'use_hard_stops': True,  # Always use hard stops
    'use_trailing_stops': True,  # Enable trailing
    'trailing_activation_pct': 0.008,  # Activate at +0.8%
    'trailing_distance_pct': 0.003,  # Trail at 0.3%

    # Move to breakeven
    'move_to_breakeven_at_pct': 0.008,  # Move to BE at +0.8%
    'breakeven_buffer_pct': 0.001,  # 0.1% buffer above BE
}

# ============================================================================
# TAKE-PROFIT CONFIGURATION - REALISTIC TARGETS
# ============================================================================

TAKE_PROFIT = {
    # Fee-aware profit targets
    # For small accounts, must beat fees + spread
    'min_profit_threshold_pct': 0.015,  # 1.5% minimum to beat fees

    # Tiered profit taking
    'tp1': {
        'pct': 0.015,  # +1.5% first target
        'exit_size': 0.50,  # Close 50%
        'action': 'move_stop_to_breakeven',
    },
    'tp2': {
        'pct': 0.025,  # +2.5% second target
        'exit_size': 0.30,  # Close 30% more (80% total)
        'action': 'activate_trailing_stop',
    },
    'tp3': {
        'pct': 0.040,  # +4.0% final target
        'exit_size': 0.20,  # Close remaining 20%
        'action': 'full_exit',
    },

    # Profit protection
    'use_time_based_exit': True,  # Exit if profit stalls
    'max_hold_time_minutes': 60,  # Max 1 hour per trade
    'min_profit_to_hold_pct': 0.010,  # Need +1% to hold past 30 min
}

# ============================================================================
# ENTRY REQUIREMENTS - STRICT FILTERING
# ============================================================================

ENTRY_REQUIREMENTS = {
    # Signal quality (require high quality)
    'min_signal_score': 5,  # Require 5/6 confirmations
    'require_all_confirmations': False,  # At least 5 of 6

    # Technical requirements (strict)
    'require_ema_alignment': True,  # Must have EMA alignment
    'require_vwap_alignment': True,  # Must align with VWAP
    'min_adx': 25,  # Strong trend required (ADX > 25)
    'min_volume_multiplier': 1.5,  # Volume must be 1.5x average

    # Spread/liquidity filters
    'max_spread_pct': 0.002,  # 0.2% max spread
    'min_liquidity_usd': 50000,  # $50k min liquidity

    # Avoid risky conditions
    'avoid_high_volatility': True,
    'max_atr_pct': 0.03,  # 3% max ATR
    'avoid_news_events': True,
    'news_cooldown_minutes': 10,
}

# ============================================================================
# TRADING MODE CONFIGURATION
# ============================================================================

# Trading mode: Independent trading (no copy trading)
TRADING_MODE = "independent"

# ============================================================================
# EXCHANGE SELECTION - FEE OPTIMIZATION
# ============================================================================

EXCHANGE_PREFERENCES = {
    # Prefer low-fee exchanges for small accounts
    'priority_order': ['kraken', 'okx', 'binance', 'coinbase'],

    # Exchange-specific settings
    'kraken': {
        'enabled': True,
        'priority': 1,  # First choice (low fees, reliable)
        'max_allocation_pct': 1.0,  # 100% allocation allowed
        'min_balance': 20.00,  # Kraken good for $20+
    },
    'okx': {
        'enabled': True,
        'priority': 2,  # Second choice (lowest fees)
        'max_allocation_pct': 0.50,  # 50% max
        'min_balance': 25.00,
    },
    'coinbase': {
        'enabled': False,  # Disabled for small accounts (high fees)
        'priority': 4,  # Last choice
        'max_allocation_pct': 0.0,  # No allocation
        'min_balance': 100.00,  # Only enable if balance > $100
    },

    # Minimum balances to use each exchange
    'use_kraken_under': 100.00,  # Use Kraken for accounts under $100
    'use_coinbase_above': 100.00,  # Only use Coinbase above $100
}

# ============================================================================
# PRO MODE SETTINGS - OPTIMIZED FOR SMALL ACCOUNTS
# ============================================================================

PRO_MODE = {
    # Enable PRO mode for better capital efficiency
    'enabled': True,

    # Reserve settings (conservative for safety)
    'min_reserve_pct': 0.20,  # Keep 20% in reserve
    'target_reserve_pct': 0.30,  # Target 30% reserve

    # Position rotation (gentle for small accounts)
    'allow_position_rotation': True,
    'min_profit_to_rotate_pct': 0.015,  # Need +1.5% to rotate
    'rotate_weakest_first': True,  # Close worst performer first

    # Capital efficiency
    'count_positions_as_capital': True,  # Count position values
    'use_total_equity_for_sizing': True,  # Use total equity
}

# ============================================================================
# SAFETY FEATURES - MAXIMUM PROTECTION
# ============================================================================

SAFETY_FEATURES = {
    # Automatic circuit breakers
    'daily_loss_circuit_breaker': True,
    'daily_loss_limit_pct': 0.02,  # Stop at 2% daily loss

    'consecutive_loss_breaker': True,
    'max_consecutive_losses': 3,  # Stop after 3 losses in a row

    'drawdown_protection': True,
    'max_drawdown_before_stop_pct': 0.08,  # Stop at 8% drawdown

    # Burn-down mode (reduce size after losses)
    'burn_down_mode': True,
    'trigger_consecutive_losses': 2,  # Trigger after 2 losses
    'burn_down_position_pct': 0.02,  # Reduce to 2% positions
    'burn_down_duration_trades': 3,  # For next 3 trades

    # Recovery mode
    'recovery_mode': True,
    'recovery_wins_required': 2,  # 2 wins to exit burn-down

    # Emergency stops
    'emergency_stop_enabled': True,
    'emergency_stop_balance': 15.00,  # Stop trading below $15

    # Profit protection
    'lock_profits_above_pct': 0.10,  # Lock profits at +10%
    'locked_profit_protection_pct': 0.50,  # Protect 50% of profit
}

# ============================================================================
# MONITORING AND ALERTS
# ============================================================================

MONITORING = {
    # Logging level
    'log_level': 'INFO',
    'log_all_trades': True,
    'log_all_signals': True,

    # Performance tracking
    'track_daily_pnl': True,
    'track_win_rate': True,
    'track_sharpe_ratio': False,  # Not relevant for small account

    # Alerts (if webhook configured)
    'alert_on_trade': False,  # Don't spam on every trade
    'alert_on_loss': True,  # Alert on losses
    'alert_on_circuit_breaker': True,  # Alert on safety stops
    'alert_on_daily_profit': True,  # Alert on daily profit
}

# ============================================================================
# TRADING PAIRS - SAFE SELECTION
# ============================================================================

TRADING_PAIRS = {
    # Only trade major, liquid pairs
    'allowed_pairs': [
        'BTC-USD', 'BTCUSD',  # Bitcoin
        'ETH-USD', 'ETHUSD',  # Ethereum
        'SOL-USD', 'SOLUSD',  # Solana
    ],

    # Blacklist risky pairs
    'blacklisted_pairs': [
        'XRP-USD', 'XRPUSD',  # High spread, low profit potential for small accounts
        # Add any other risky pairs here
    ],

    # Pair-specific limits
    'max_positions_per_pair': 1,  # One position per pair max
    'prefer_btc_eth': True,  # Prefer BTC/ETH over others
}

# ============================================================================
# EXECUTION SETTINGS
# ============================================================================

EXECUTION = {
    # Order types (prefer limit for fee savings)
    'default_order_type': 'limit',
    'use_market_on_urgency': False,  # Never use market orders
    'limit_order_timeout_seconds': 30,

    # Slippage protection
    'max_slippage_pct': 0.002,  # 0.2% max slippage
    'cancel_order_on_slippage': True,

    # Timing
    'scan_interval_seconds': 300,  # Scan every 5 minutes
    'avoid_first_candle_seconds': 10,  # Wait 10s after new candle
}

# ============================================================================
# PRESET METADATA
# ============================================================================

PRESET_INFO = {
    'name': 'Safe Small-Account Preset',
    'version': '1.0',
    'description': 'Ultra-conservative preset for $20-$100 accounts',
    'target_accounts': '$20-$100',
    'risk_level': 'Very Low',
    'experience_level': 'Beginner-Friendly',
    'independent_trading': True,
    'fee_optimized': True,
    'author': 'NIJA Trading Systems',
    'created': '2026-01-20',
}

# ============================================================================
# PRESET APPLICATION FUNCTION
# ============================================================================

def get_environment_variables():
    """
    Get environment variables for small-account preset.

    Returns:
        Dict of environment variable names and values
    """
    return {
        'TRADING_MODE': 'independent',
        'PRO_MODE': 'true',
        'MINIMUM_TRADING_BALANCE': str(ACCOUNT_SIZE['min_balance']),
        'MIN_CASH_TO_BUY': str(POSITION_SIZING['absolute_min_position_usd']),
        'MAX_CONCURRENT_POSITIONS': str(RISK_LIMITS['max_concurrent_positions']),
        'DISABLED_PAIRS': ','.join(TRADING_PAIRS['blacklisted_pairs']),
    }


def apply_small_account_preset(set_env_vars=True):
    """
    Apply safe small-account preset configuration.

    Args:
        set_env_vars: If True, sets environment variables. If False, only returns config.

    Returns:
        Dict with all preset configurations and environment variables
    """
    import os

    # Get environment variables
    env_vars = get_environment_variables()

    # Optionally set environment variables
    if set_env_vars:
        for key, value in env_vars.items():
            os.environ[key] = value

    # Return all preset configs
    return {
        'account_size': ACCOUNT_SIZE,
        'risk_limits': RISK_LIMITS,
        'position_sizing': POSITION_SIZING,
        'stop_loss': STOP_LOSS,
        'take_profit': TAKE_PROFIT,
        'entry_requirements': ENTRY_REQUIREMENTS,
        'trading_mode': TRADING_MODE,
        'exchange_preferences': EXCHANGE_PREFERENCES,
        'pro_mode': PRO_MODE,
        'safety_features': SAFETY_FEATURES,
        'monitoring': MONITORING,
        'trading_pairs': TRADING_PAIRS,
        'execution': EXECUTION,
        'preset_info': PRESET_INFO,
        'environment_variables': env_vars,
    }


def get_preset_summary():
    """Get human-readable summary of preset settings."""
    return f"""
╔══════════════════════════════════════════════════════════════════════════╗
║                  NIJA SAFE SMALL-ACCOUNT PRESET                          ║
║                         Version 1.0                                       ║
╚══════════════════════════════════════════════════════════════════════════╝

📊 TARGET ACCOUNTS: ${ACCOUNT_SIZE['min_balance']:.0f} - ${ACCOUNT_SIZE['max_balance']:.0f}
🎯 RECOMMENDED START: ${ACCOUNT_SIZE['recommended_starting']:.0f}

🛡️  RISK MANAGEMENT:
   • Max Risk Per Trade: {RISK_LIMITS['max_risk_per_trade_pct']*100:.1f}%
   • Max Position Size: {RISK_LIMITS['max_position_size_pct']*100:.0f}%
   • Max Daily Loss: {RISK_LIMITS['max_daily_loss_pct']*100:.0f}%
   • Max Concurrent Positions: {RISK_LIMITS['max_concurrent_positions']}
   • Emergency Stop: ${ACCOUNT_SIZE['emergency_stop_balance']:.0f}

💰 POSITION SIZING:
   • Base Position: {POSITION_SIZING['base_position_pct']*100:.0f}%
   • Position Range: ${POSITION_SIZING['absolute_min_position_usd']:.0f} - ${POSITION_SIZING['absolute_max_position_usd']:.0f}
   • Signal Quality: Require 5/6 confirmations

🎯 PROFIT TARGETS:
   • TP1: +{TAKE_PROFIT['tp1']['pct']*100:.1f}% (close {TAKE_PROFIT['tp1']['exit_size']*100:.0f}%)
   • TP2: +{TAKE_PROFIT['tp2']['pct']*100:.1f}% (close {TAKE_PROFIT['tp2']['exit_size']*100:.0f}%)
   • TP3: +{TAKE_PROFIT['tp3']['pct']*100:.1f}% (close {TAKE_PROFIT['tp3']['exit_size']*100:.0f}%)

🛑 STOP-LOSS:
   • Default Stop: {STOP_LOSS['default_stop_pct']*100:.1f}%
   • Range: {STOP_LOSS['min_stop_pct']*100:.1f}% - {STOP_LOSS['max_stop_pct']*100:.1f}%
   • Trailing Stop: Active at +{STOP_LOSS['trailing_activation_pct']*100:.1f}%

⚙️  TRADING MODE:
   • Mode: {TRADING_MODE}
   • Independent: Each account trades independently

🏦 EXCHANGE PRIORITY:
   1. {EXCHANGE_PREFERENCES['priority_order'][0].upper()} (Primary)
   2. {EXCHANGE_PREFERENCES['priority_order'][1].upper()} (Secondary)
   • Coinbase: {'Enabled' if EXCHANGE_PREFERENCES['coinbase']['enabled'] else 'Disabled for small accounts'}

⚡ PRO MODE:
   • Enabled: {PRO_MODE['enabled']}
   • Reserve: {PRO_MODE['min_reserve_pct']*100:.0f}% minimum
   • Position Rotation: {PRO_MODE['allow_position_rotation']}

🚨 SAFETY FEATURES:
   • Circuit Breakers: Active
   • Consecutive Loss Limit: {SAFETY_FEATURES['max_consecutive_losses']} trades
   • Burn-Down Mode: Auto-reduces size after losses
   • Emergency Stop: ${SAFETY_FEATURES['emergency_stop_balance']:.0f}

📈 TRADING PAIRS:
   • BTC-USD, ETH-USD, SOL-USD (liquid majors only)
   • Blacklisted: {', '.join(TRADING_PAIRS['blacklisted_pairs'])}

═══════════════════════════════════════════════════════════════════════════

This preset is optimized for:
✅ Capital preservation
✅ Controlled risk exposure
✅ Fee-efficient trading
✅ Copy trading with proportional sizing
✅ Maximum safety for small accounts

To activate this preset, use: apply_small_account_preset()
"""


if __name__ == "__main__":
    # Print preset summary
    print(get_preset_summary())

    # Apply preset
    config = apply_small_account_preset()
    print(f"\n✅ Preset applied successfully!")
    print(f"   Account Size: ${config['account_size']['min_balance']:.0f} - ${config['account_size']['max_balance']:.0f}")
    print(f"   Max Risk/Trade: {config['risk_limits']['max_risk_per_trade_pct']*100:.1f}%")
    print(f"   Trading Mode: {config['trading_mode']}")
