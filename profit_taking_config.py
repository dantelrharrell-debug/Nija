"""
NIJA Profit-Taking Configuration
Optimized settings for consistent profit capture with minimal drawback
"""

# ==============================================================================
# PROFIT-TAKING STRATEGY SELECTION
# ==============================================================================

# Primary strategy: 'scaled', 'trailing_stop', 'fixed_percentage', or 'adaptive'
PROFIT_TAKING_STRATEGY = 'scaled'

# ==============================================================================
# SCALED PROFIT-TAKING CONFIGURATION (RECOMMENDED)
# ==============================================================================

# Three-tier profit taking system
# Each tier exits a portion of the position at increasing profit levels
SCALED_EXITS = {
    'tier_1': {
        'profit_target_pct': 0.5,    # 0.5% profit
        'exit_percentage': 50,        # Exit 50% of position
        'move_stop_to_breakeven': True,
        'description': 'Quick profit lock + risk elimination'
    },
    'tier_2': {
        'profit_target_pct': 1.0,    # 1.0% profit
        'exit_percentage': 25,        # Exit 25% more (75% total)
        'adjust_trailing_stop': True,
        'description': 'Secure additional gains'
    },
    'tier_3': {
        'profit_target_pct': 2.0,    # 2.0% profit
        'exit_percentage': 25,        # Exit final 25% (100% closed)
        'description': 'Maximum target exit'
    }
}

# Alternative aggressive configuration (faster exits, lower targets)
SCALED_EXITS_AGGRESSIVE = {
    'tier_1': {
        'profit_target_pct': 0.3,    # 0.3% profit
        'exit_percentage': 40,        # Exit 40%
        'move_stop_to_breakeven': True,
    },
    'tier_2': {
        'profit_target_pct': 0.6,    # 0.6% profit  
        'exit_percentage': 30,        # Exit 30% more (70% total)
    },
    'tier_3': {
        'profit_target_pct': 1.2,    # 1.2% profit
        'exit_percentage': 30,        # Exit final 30% (100% closed)
    }
}

# Alternative conservative configuration (slower exits, higher targets)
SCALED_EXITS_CONSERVATIVE = {
    'tier_1': {
        'profit_target_pct': 1.0,    # 1.0% profit
        'exit_percentage': 33,        # Exit 33%
        'move_stop_to_breakeven': True,
    },
    'tier_2': {
        'profit_target_pct': 2.0,    # 2.0% profit
        'exit_percentage': 33,        # Exit 33% more (66% total)
    },
    'tier_3': {
        'profit_target_pct': 3.5,    # 3.5% profit
        'exit_percentage': 34,        # Exit final 34% (100% closed)
    }
}

# ==============================================================================
# TRAILING STOP CONFIGURATION
# ==============================================================================

TRAILING_STOP_CONFIG = {
    'enabled': True,
    'activation_profit_pct': 0.5,     # Activate after 0.5% profit
    'trailing_distance_pct': 0.3,     # Trail 0.3% below peak
    'use_atr_based': False,           # Use ATR instead of percentage
    'atr_multiplier': 1.5,            # If ATR-based, trail 1.5x ATR
    'max_drawback_from_peak': 0.5,   # Max 0.5% drawback from peak before exit
}

# ==============================================================================
# FIXED PERCENTAGE CONFIGURATION
# ==============================================================================

FIXED_PROFIT_TARGET = {
    'target_pct': 1.5,                # Single exit at 1.5% profit
    'use_trailing_after': True,       # Use trailing stop after target hit
}

# ==============================================================================
# ADAPTIVE PROFIT-TAKING (ACCOUNT BALANCE BASED)
# ==============================================================================

# Adjust profit targets based on account size
ADAPTIVE_TARGETS = {
    'small_account': {
        'balance_max': 100,
        'tier_1_target': 0.4,         # Lower targets for small accounts
        'tier_2_target': 0.8,
        'tier_3_target': 1.5,
    },
    'medium_account': {
        'balance_min': 100,
        'balance_max': 500,
        'tier_1_target': 0.5,
        'tier_2_target': 1.0,
        'tier_3_target': 2.0,
    },
    'large_account': {
        'balance_min': 500,
        'tier_1_target': 0.6,         # Higher targets for larger accounts
        'tier_2_target': 1.2,
        'tier_3_target': 2.5,
    }
}

# ==============================================================================
# RISK MANAGEMENT OVERRIDES
# ==============================================================================

# Maximum profit giveback before forced exit
MAX_PROFIT_DRAWBACK_PCT = 50         # Force exit if giving back >50% of peak profit

# Minimum profit to protect (won't exit below this if in profit)
MIN_PROFIT_PROTECTION_PCT = 0.2      # Protect at least 0.2% profit

# Time-based exit (force close after X hours in profit)
TIME_BASED_EXIT = {
    'enabled': False,
    'max_hold_hours': 24,            # Force exit after 24 hours
    'min_profit_required': 0.3,      # Only if at least 0.3% profit
}

# ==============================================================================
# FEE ADJUSTMENT
# ==============================================================================

# Coinbase Advanced Trade fees
COINBASE_FEES = {
    'taker_fee_pct': 0.6,            # 0.6% taker fee
    'maker_fee_pct': 0.4,            # 0.4% maker fee (limit orders)
}

# Minimum profit after fees
# Profit target must exceed: entry_fee + exit_fee + buffer
MIN_NET_PROFIT_AFTER_FEES = 0.3      # Minimum 0.3% net profit

# Adjust targets to account for fees
FEE_ADJUSTED_TARGETS = {
    'tier_1_adjusted': 0.5 + (COINBASE_FEES['taker_fee_pct'] * 2),  # ~1.7%
    'tier_2_adjusted': 1.0 + (COINBASE_FEES['taker_fee_pct'] * 2),  # ~2.2%
    'tier_3_adjusted': 2.0 + (COINBASE_FEES['taker_fee_pct'] * 2),  # ~3.2%
}

# ==============================================================================
# EMERGENCY SETTINGS
# ==============================================================================

# Force exit all positions if account drops below this threshold
EMERGENCY_EXIT_BALANCE_THRESHOLD = 25.0  # Exit all if balance < $25

# Disable new entries but allow profit-taking on existing positions
SELL_ONLY_MODE_THRESHOLD = 30.0          # Sell-only if balance < $30

# ==============================================================================
# LOGGING AND ALERTS
# ==============================================================================

PROFIT_TAKING_LOGGING = {
    'log_all_exits': True,
    'log_missed_targets': True,       # Log when price reached target but didn't exit
    'log_profit_giveback': True,      # Log when giving back >20% of peak
    'alert_on_large_exit': True,      # Alert when exiting >$50 position
}

# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def get_active_scaled_config(mode='default'):
    """Get the active scaled exit configuration based on mode"""
    if mode == 'aggressive':
        return SCALED_EXITS_AGGRESSIVE
    elif mode == 'conservative':
        return SCALED_EXITS_CONSERVATIVE
    else:
        return SCALED_EXITS

def get_adaptive_targets(account_balance):
    """Get profit targets based on account balance"""
    if account_balance < ADAPTIVE_TARGETS['small_account']['balance_max']:
        return ADAPTIVE_TARGETS['small_account']
    elif account_balance < ADAPTIVE_TARGETS['medium_account']['balance_max']:
        return ADAPTIVE_TARGETS['medium_account']
    else:
        return ADAPTIVE_TARGETS['large_account']

def calculate_fee_adjusted_target(base_target_pct):
    """Calculate profit target adjusted for fees"""
    total_fees = COINBASE_FEES['taker_fee_pct'] * 2  # Entry + Exit
    return base_target_pct + total_fees

def should_force_exit(current_balance, peak_profit_pct, current_profit_pct):
    """Check if emergency exit conditions are met"""
    # Emergency balance threshold
    if current_balance < EMERGENCY_EXIT_BALANCE_THRESHOLD:
        return True, "Emergency balance threshold"
    
    # Excessive profit giveback
    if peak_profit_pct > 0:
        drawback_pct = ((peak_profit_pct - current_profit_pct) / peak_profit_pct) * 100
        if drawback_pct > MAX_PROFIT_DRAWBACK_PCT:
            return True, f"Profit drawback {drawback_pct:.1f}% > {MAX_PROFIT_DRAWBACK_PCT}%"
    
    return False, None

# ==============================================================================
# RECOMMENDED CONFIGURATION
# ==============================================================================

RECOMMENDED_CONFIG = {
    'strategy': 'scaled',
    'mode': 'default',  # or 'aggressive' or 'conservative'
    'use_trailing_stop': True,
    'use_fee_adjustment': True,
    'enable_adaptive_targets': False,  # Set True for balance-based targets
    'enable_emergency_exits': True,
}

# ==============================================================================
# CONFIGURATION SUMMARY
# ==============================================================================

def print_active_config():
    """Print the currently active profit-taking configuration"""
    print("="*70)
    print("NIJA PROFIT-TAKING CONFIGURATION")
    print("="*70)
    print(f"Primary Strategy: {PROFIT_TAKING_STRATEGY}")
    print(f"")
    
    if PROFIT_TAKING_STRATEGY == 'scaled':
        config = get_active_scaled_config(RECOMMENDED_CONFIG['mode'])
        print(f"Scaled Exit Configuration ({RECOMMENDED_CONFIG['mode'].upper()} mode):")
        print(f"")
        for tier, settings in config.items():
            print(f"  {tier.upper()}:")
            print(f"    Profit Target: {settings['profit_target_pct']}%")
            print(f"    Exit Amount: {settings['exit_percentage']}%")
            if settings.get('move_stop_to_breakeven'):
                print(f"    Action: Move stop to breakeven")
            print(f"")
    
    print(f"Trailing Stop: {'ENABLED' if TRAILING_STOP_CONFIG['enabled'] else 'DISABLED'}")
    if TRAILING_STOP_CONFIG['enabled']:
        print(f"  Activation: {TRAILING_STOP_CONFIG['activation_profit_pct']}% profit")
        print(f"  Distance: {TRAILING_STOP_CONFIG['trailing_distance_pct']}%")
    
    print(f"")
    print(f"Fee Adjustment: {'ENABLED' if RECOMMENDED_CONFIG['use_fee_adjustment'] else 'DISABLED'}")
    print(f"Emergency Exits: {'ENABLED' if RECOMMENDED_CONFIG['enable_emergency_exits'] else 'DISABLED'}")
    print(f"  Threshold: ${EMERGENCY_EXIT_BALANCE_THRESHOLD}")
    print("="*70)

if __name__ == "__main__":
    print_active_config()
