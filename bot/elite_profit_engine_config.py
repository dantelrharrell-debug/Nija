"""
Elite Profit Engine v2 Configuration
=====================================

Centralized configuration for all profit optimization subsystems.

Author: NIJA Trading Systems
Version: 2.0 - Elite Profit Engine
Date: January 29, 2026
"""

# =============================================================================
# PROFILE PRESETS
# =============================================================================

CONSERVATIVE_PROFILE = {
    'name': 'Conservative',
    'description': 'Low risk, steady growth, capital preservation focused',

    'volatility_sizer': {
        'base_position_pct': 0.03,  # 3% base position
        'min_position_pct': 0.02,  # 2% minimum
        'max_position_pct': 0.06,  # 6% maximum
    },

    'capital_rotation': {
        'min_strategy_allocation': 0.20,  # 20% minimum per strategy
        'max_strategy_allocation': 0.50,  # 50% maximum per strategy
    },

    'leverage': {
        'leverage_mode': 'conservative',  # 1x-2x leverage
        'absolute_max_leverage': 2.0,
        'max_drawdown_pct': 0.10,  # 10% max drawdown
        'min_win_rate': 0.55,  # 55% minimum win rate
    },

    'profit_locking': {
        'daily_target_pct': 0.015,  # 1.5% daily target
        'stop_trading_at_target_pct': 200,  # Stop at 200% of target (3%)
    },

    'frequency_optimizer': {
        'base_scan_interval': 180,  # 3 minutes
    },

    'compounding_strategy': 'conservative',  # 50% reinvest, 50% preserve
}


MODERATE_PROFILE = {
    'name': 'Moderate',
    'description': 'Balanced risk/reward, standard configuration',

    'volatility_sizer': {
        'base_position_pct': 0.05,  # 5% base position
        'min_position_pct': 0.02,  # 2% minimum
        'max_position_pct': 0.10,  # 10% maximum
    },

    'capital_rotation': {
        'min_strategy_allocation': 0.15,  # 15% minimum per strategy
        'max_strategy_allocation': 0.60,  # 60% maximum per strategy
    },

    'leverage': {
        'leverage_mode': 'moderate',  # 1x-3x leverage
        'absolute_max_leverage': 3.0,
        'max_drawdown_pct': 0.15,  # 15% max drawdown
        'min_win_rate': 0.50,  # 50% minimum win rate
    },

    'profit_locking': {
        'daily_target_pct': 0.02,  # 2% daily target
        'stop_trading_at_target_pct': None,  # Never stop (keep trading)
    },

    'frequency_optimizer': {
        'base_scan_interval': 150,  # 2.5 minutes
    },

    'compounding_strategy': 'moderate',  # 75% reinvest, 25% preserve
}


AGGRESSIVE_PROFILE = {
    'name': 'Aggressive',
    'description': 'High risk/reward, maximum profit pursuit',

    'volatility_sizer': {
        'base_position_pct': 0.08,  # 8% base position
        'min_position_pct': 0.03,  # 3% minimum
        'max_position_pct': 0.15,  # 15% maximum
    },

    'capital_rotation': {
        'min_strategy_allocation': 0.10,  # 10% minimum per strategy
        'max_strategy_allocation': 0.70,  # 70% maximum per strategy
    },

    'leverage': {
        'leverage_mode': 'aggressive',  # 1x-5x leverage
        'absolute_max_leverage': 5.0,
        'max_drawdown_pct': 0.20,  # 20% max drawdown
        'min_win_rate': 0.45,  # 45% minimum win rate
    },

    'profit_locking': {
        'daily_target_pct': 0.03,  # 3% daily target
        'stop_trading_at_target_pct': None,  # Never stop
    },

    'frequency_optimizer': {
        'base_scan_interval': 120,  # 2 minutes (faster scanning)
    },

    'compounding_strategy': 'aggressive',  # 90% reinvest, 10% preserve
}


ELITE_PERFORMANCE_PROFILE = {
    'name': 'Elite Performance',
    'description': 'Maximum optimization, all features enabled',

    'volatility_sizer': {
        'base_position_pct': 0.06,  # 6% base position
        'min_position_pct': 0.02,  # 2% minimum
        'max_position_pct': 0.12,  # 12% maximum
        'atr_lookback': 20,
    },

    'capital_rotation': {
        'min_strategy_allocation': 0.10,  # 10% minimum per strategy
        'max_strategy_allocation': 0.65,  # 65% maximum per strategy
    },

    'leverage': {
        'leverage_mode': 'moderate',  # Moderate leverage with elite optimization
        'absolute_max_leverage': 3.5,
        'max_drawdown_pct': 0.15,  # 15% max drawdown
        'min_win_rate': 0.52,  # 52% minimum win rate
    },

    'profit_locking': {
        'daily_target_pct': 0.025,  # 2.5% daily target
        'stop_trading_at_target_pct': None,  # Never stop - keep compounding
    },

    'frequency_optimizer': {
        'base_scan_interval': 140,  # 2.33 minutes
    },

    'compounding_strategy': 'moderate',  # 75% reinvest, 25% preserve
}


# =============================================================================
# ENVIRONMENT-SPECIFIC OVERRIDES
# =============================================================================

PAPER_TRADING_OVERRIDES = {
    'leverage': {
        'leverage_mode': 'disabled',  # No leverage in paper trading
    }
}


LIVE_TRADING_OVERRIDES = {
    # Add any live-specific safety overrides here
    'leverage': {
        'absolute_max_leverage': 3.0,  # Cap at 3x even in aggressive mode
    }
}


# =============================================================================
# DEFAULT CONFIGURATION
# =============================================================================

DEFAULT_CONFIG = MODERATE_PROFILE


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_config_profile(profile_name: str = 'moderate') -> dict:
    """
    Get configuration profile by name

    Args:
        profile_name: Profile name (conservative/moderate/aggressive/elite)

    Returns:
        Configuration dictionary
    """
    profiles = {
        'conservative': CONSERVATIVE_PROFILE,
        'moderate': MODERATE_PROFILE,
        'aggressive': AGGRESSIVE_PROFILE,
        'elite': ELITE_PERFORMANCE_PROFILE,
    }

    profile = profiles.get(profile_name.lower(), MODERATE_PROFILE)
    return profile.copy()


def get_environment_config(base_profile: str = 'moderate', environment: str = 'paper') -> dict:
    """
    Get configuration with environment-specific overrides

    Args:
        base_profile: Base profile name
        environment: Environment (paper/live)

    Returns:
        Configuration dictionary with overrides applied
    """
    config = get_config_profile(base_profile)

    # Apply environment-specific overrides
    if environment.lower() == 'paper':
        overrides = PAPER_TRADING_OVERRIDES
    elif environment.lower() == 'live':
        overrides = LIVE_TRADING_OVERRIDES
    else:
        overrides = {}

    # Deep merge overrides
    for key, value in overrides.items():
        if key in config and isinstance(value, dict):
            config[key].update(value)
        else:
            config[key] = value

    return config


def validate_config(config: dict) -> tuple:
    """
    Validate configuration settings

    Args:
        config: Configuration dictionary

    Returns:
        Tuple of (is_valid, errors_list)
    """
    errors = []

    # Validate volatility sizer
    if 'volatility_sizer' in config:
        vs = config['volatility_sizer']
        if vs.get('min_position_pct', 0) > vs.get('max_position_pct', 1):
            errors.append("min_position_pct must be <= max_position_pct")

    # Validate leverage
    if 'leverage' in config:
        lev = config['leverage']
        valid_modes = ['disabled', 'conservative', 'moderate', 'aggressive']
        if lev.get('leverage_mode') not in valid_modes:
            errors.append(f"Invalid leverage_mode. Must be one of: {valid_modes}")

        if lev.get('absolute_max_leverage', 0) > 10:
            errors.append("absolute_max_leverage should not exceed 10x for safety")

    # Validate profit locking
    if 'profit_locking' in config:
        pl = config['profit_locking']
        if pl.get('daily_target_pct', 0) <= 0:
            errors.append("daily_target_pct must be positive")
        if pl.get('daily_target_pct', 0) > 0.10:  # 10% daily target is very aggressive
            errors.append("daily_target_pct > 10% is unrealistic - consider lowering")

    # Validate compounding strategy
    if 'compounding_strategy' in config:
        valid_strategies = ['conservative', 'moderate', 'aggressive', 'full_compound']
        if config['compounding_strategy'] not in valid_strategies:
            errors.append(f"Invalid compounding_strategy. Must be one of: {valid_strategies}")

    is_valid = len(errors) == 0
    return is_valid, errors


def print_config_summary(config: dict):
    """
    Print configuration summary

    Args:
        config: Configuration dictionary
    """
    print("\n" + "=" * 80)
    print(f"ELITE PROFIT ENGINE V2 CONFIGURATION: {config.get('name', 'Custom')}")
    print("=" * 80)
    print(f"Description: {config.get('description', 'N/A')}")
    print()

    print("Position Sizing:")
    if 'volatility_sizer' in config:
        vs = config['volatility_sizer']
        print(f"  Base: {vs.get('base_position_pct', 0)*100:.1f}%")
        print(f"  Range: {vs.get('min_position_pct', 0)*100:.1f}% - {vs.get('max_position_pct', 0)*100:.1f}%")

    print("\nLeverage:")
    if 'leverage' in config:
        lev = config['leverage']
        print(f"  Mode: {lev.get('leverage_mode', 'N/A').upper()}")
        print(f"  Max: {lev.get('absolute_max_leverage', 1):.1f}x")
        print(f"  Max Drawdown: {lev.get('max_drawdown_pct', 0)*100:.1f}%")

    print("\nProfit Management:")
    if 'profit_locking' in config:
        pl = config['profit_locking']
        print(f"  Daily Target: {pl.get('daily_target_pct', 0)*100:.1f}%")
        stop_pct = pl.get('stop_trading_at_target_pct')
        print(f"  Stop Trading At: {f'{stop_pct}% of target' if stop_pct else 'Never'}")

    print(f"\nCompounding: {config.get('compounding_strategy', 'N/A').upper()}")

    print("\nFrequency:")
    if 'frequency_optimizer' in config:
        fo = config['frequency_optimizer']
        interval = fo.get('base_scan_interval', 150)
        print(f"  Base Scan Interval: {interval}s ({interval/60:.1f} min)")

    print("=" * 80 + "\n")


# =============================================================================
# USAGE EXAMPLES
# =============================================================================

if __name__ == "__main__":
    # Example 1: Get moderate profile
    config = get_config_profile('moderate')
    print_config_summary(config)

    # Example 2: Get elite profile for paper trading
    elite_config = get_environment_config('elite', 'paper')
    print_config_summary(elite_config)

    # Example 3: Validate configuration
    is_valid, errors = validate_config(config)
    if is_valid:
        print("✅ Configuration is valid")
    else:
        print("❌ Configuration errors:")
        for error in errors:
            print(f"  - {error}")

    # Example 4: Show all profiles
    print("\n" + "=" * 80)
    print("AVAILABLE PROFILES")
    print("=" * 80)
    for name in ['conservative', 'moderate', 'aggressive', 'elite']:
        prof = get_config_profile(name)
        print(f"\n{prof['name']}:")
        print(f"  {prof['description']}")
