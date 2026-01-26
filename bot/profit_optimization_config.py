"""
NIJA Profit Optimization Configuration
=======================================

Enhanced configuration to maximize profitability on Coinbase and Kraken.

Key Features:
1. Enhanced entry scoring (0-100 weighted system vs basic 1-5)
2. Market regime detection (adaptive parameters)
3. Faster profit-taking (stepped exits at multiple levels)
4. Exchange-specific fee optimization
5. Improved position sizing for capital efficiency

Author: NIJA Trading Systems
Version: 1.0
Date: January 25, 2026
"""

import logging
from typing import Dict

logger = logging.getLogger("nija.profit_optimization")


# ============================================================================
# VALIDATION CONSTANTS
# ============================================================================

# Tolerance for floating-point comparisons in validation
WEIGHT_TOLERANCE = 0.01  # 1% tolerance for weight sum validation
ALLOCATION_TOLERANCE = 0.01  # 1% tolerance for capital allocation sum validation


# ============================================================================
# ENHANCED ENTRY SCORING CONFIGURATION
# ============================================================================

ENHANCED_SCORING_CONFIG = {
    # Enable enhanced scoring (0-100 weighted system)
    'use_enhanced_scoring': True,
    
    # Minimum score to enter trade (out of 100)
    # PROFITABILITY FIX (Jan 26, 2026): Increased thresholds to only take high-quality trades
    # 75 = very good setup, 85+ = excellent (filters out marginal 60-70 trades that caused losses)
    'min_score_threshold': 75,  # Stricter threshold to improve win rate
    'excellent_score_threshold': 85,  # Increase position size on excellent setups
    
    # Score weights (must sum to 100)
    'scoring_weights': {
        'trend_strength': 25,      # ADX, EMA alignment
        'momentum': 20,             # RSI, MACD direction
        'price_action': 20,         # Candlestick patterns
        'volume': 15,               # Volume confirmation
        'market_structure': 20,     # Support/resistance levels
    }
}


# ============================================================================
# MARKET REGIME DETECTION CONFIGURATION
# ============================================================================

REGIME_DETECTION_CONFIG = {
    # Enable market regime detection
    'use_regime_detection': True,
    
    # Regime classification thresholds
    'trending_adx_min': 25,        # ADX > 25 = trending market
    'ranging_adx_max': 20,         # ADX < 20 = ranging market
    'volatile_atr_threshold': 0.03, # 3% ATR/price = volatile
    
    # Regime-specific parameters
    # PROFITABILITY FIX (Jan 26, 2026): Increased all min_entry_score thresholds by 15 points
    'regime_params': {
        'trending': {
            'min_entry_score': 75,               # Stricter threshold (was 60)
            'position_size_multiplier': 1.2,     # Increase size by 20%
            'trailing_stop_distance': 1.5,       # Wider trailing stop
            'take_profit_multiplier': 1.5,       # Higher profit targets
        },
        'ranging': {
            'min_entry_score': 80,               # Very selective (was 65)
            'position_size_multiplier': 0.8,     # Reduce size by 20%
            'trailing_stop_distance': 1.0,       # Tighter trailing stop
            'take_profit_multiplier': 0.8,       # Take profits faster
        },
        'volatile': {
            'min_entry_score': 85,               # Extremely selective (was 70)
            'position_size_multiplier': 0.7,     # Reduce size by 30%
            'trailing_stop_distance': 2.0,       # Much wider stops
            'take_profit_multiplier': 1.0,       # Normal profit targets
        }
    }
}


# ============================================================================
# STEPPED PROFIT-TAKING CONFIGURATION (V7.2 STYLE)
# ============================================================================

STEPPED_PROFIT_CONFIG = {
    # Enable stepped profit-taking (partial exits)
    'enable_stepped_exits': True,
    
    # Exit levels: {profit_pct: portion_to_exit}
    # Example: At 1% profit, exit 15% of position
    'coinbase_exit_levels': {
        0.015: 0.10,  # Exit 10% at 1.5% profit (covers fees + small profit)
        0.025: 0.15,  # Exit 15% at 2.5% profit (good profit margin)
        0.035: 0.25,  # Exit 25% at 3.5% profit (excellent profit)
        0.050: 0.50,  # Exit 50% at 5.0% profit (let rest run)
    },
    
    # Kraken has lower fees, so can take profits sooner
    # Note: Exit levels are lower percentages to reflect the 53% fee savings
    # (0.67% fees vs 1.4% on Coinbase allows for faster profit-taking)
    'kraken_exit_levels': {
        0.008: 0.10,  # Exit 10% at 0.8% profit (covers fees)
        0.015: 0.15,  # Exit 15% at 1.5% profit
        0.025: 0.25,  # Exit 25% at 2.5% profit
        0.040: 0.50,  # Exit 50% at 4.0% profit (let rest run)
    }
}


# ============================================================================
# EXCHANGE-SPECIFIC FEE OPTIMIZATION
# ============================================================================

FEE_OPTIMIZATION_CONFIG = {
    # Minimum profit targets to beat fees
    'coinbase': {
        'min_profit_target_pct': 0.016,  # 1.6% minimum (covers 1.4% fees + small profit)
        'preferred_profit_target_pct': 0.025,  # 2.5% preferred target
        'taker_fee_pct': 0.006,  # 0.6% taker fee
        'round_trip_cost_pct': 0.014,  # 1.4% total round-trip
    },
    'kraken': {
        'min_profit_target_pct': 0.008,  # 0.8% minimum (covers 0.67% fees + small profit)
        'preferred_profit_target_pct': 0.015,  # 1.5% preferred target
        'taker_fee_pct': 0.0026,  # 0.26% taker fee
        'round_trip_cost_pct': 0.0067,  # 0.67% total round-trip
    },
    
    # Broker routing preferences based on position size
    'routing_rules': {
        'prefer_kraken_for_small_positions': True,  # Route small positions to Kraken (lower fees)
        'small_position_threshold_usd': 100,  # Positions under $100
        'prefer_coinbase_for_liquidity': True,  # Route large positions to Coinbase (more liquid)
        'large_position_threshold_usd': 500,  # Positions over $500
    }
}


# ============================================================================
# POSITION SIZING OPTIMIZATION
# ============================================================================

POSITION_SIZING_CONFIG = {
    # Conservative position sizing for capital efficiency
    'min_position_pct': 0.02,  # 2% minimum per position
    'max_position_pct': 0.10,  # 10% maximum per position (was 20%, reducing for more positions)
    'max_total_exposure': 0.80,  # 80% maximum total exposure
    
    # Dynamic sizing based on signal quality
    'use_dynamic_sizing': True,
    'signal_score_multipliers': {
        60: 0.80,  # Good setup = 80% of base size
        70: 1.00,  # Very good setup = 100% of base size
        80: 1.20,  # Excellent setup = 120% of base size
        90: 1.40,  # Outstanding setup = 140% of base size
    },
    
    # ADX-based position sizing (trend strength)
    'use_adx_sizing': True,
    'adx_size_map': {
        20: 0.02,  # Weak trend = 2% position
        25: 0.04,  # Moderate trend = 4% position
        30: 0.06,  # Strong trend = 6% position
        40: 0.08,  # Very strong trend = 8% position
        50: 0.10,  # Extremely strong trend = 10% position
    }
}


# ============================================================================
# MULTI-EXCHANGE OPTIMIZATION
# ============================================================================

MULTI_EXCHANGE_CONFIG = {
    # Capital allocation across exchanges
    'capital_allocation': {
        'coinbase': 0.50,  # 50% of capital to Coinbase (most reliable)
        'kraken': 0.50,    # 50% of capital to Kraken (lower fees)
    },
    
    # Market scanning optimization
    'distribute_scanning': True,  # Split markets across exchanges
    'scan_delay_per_exchange': 4.0,  # 4s delay per exchange (8s total)
    
    # Exchange-specific minimums
    'min_position_usd': {
        'coinbase': 5.0,   # $5 minimum on Coinbase
        'kraken': 10.0,    # $10 minimum on Kraken (exchange requirement)
    }
}


# ============================================================================
# ADVANCED FEATURES
# ============================================================================

ADVANCED_FEATURES_CONFIG = {
    # Enable aggressive profit-taking mode
    'aggressive_profit_taking': True,
    
    # Enable pro mode features (if available)
    'enable_pro_mode': True,
    
    # Enable emergency liquidation for capital preservation
    'enable_emergency_liquidation': True,
    
    # Enable copy trading (for multi-account setups)
    'enable_copy_trading': True,
}


# ============================================================================
# MASTER CONFIGURATION BUILDER
# ============================================================================

def get_profit_optimization_config() -> Dict:
    """
    Build complete profit optimization configuration.
    
    Returns:
        Dict with all optimization parameters
    """
    config = {}
    
    # Merge all config sections
    config.update(ENHANCED_SCORING_CONFIG)
    config.update(REGIME_DETECTION_CONFIG)
    config.update(STEPPED_PROFIT_CONFIG)
    config['fee_optimization'] = FEE_OPTIMIZATION_CONFIG
    config.update(POSITION_SIZING_CONFIG)
    config['multi_exchange'] = MULTI_EXCHANGE_CONFIG
    config.update(ADVANCED_FEATURES_CONFIG)
    
    logger.info("=" * 70)
    logger.info("🚀 PROFIT OPTIMIZATION CONFIGURATION LOADED")
    logger.info("=" * 70)
    logger.info("✅ Enhanced entry scoring: ENABLED (0-100 weighted system)")
    logger.info("✅ Market regime detection: ENABLED (adaptive parameters)")
    logger.info("✅ Stepped profit-taking: ENABLED (partial exits)")
    logger.info("✅ Fee optimization: ENABLED (exchange-specific targets)")
    logger.info("✅ Dynamic position sizing: ENABLED (signal + ADX based)")
    logger.info("✅ Multi-exchange optimization: ENABLED (Coinbase + Kraken)")
    logger.info("=" * 70)
    
    return config


def get_exchange_specific_config(exchange: str) -> Dict:
    """
    Get exchange-specific configuration.
    
    Args:
        exchange: Exchange name ('coinbase' or 'kraken')
        
    Returns:
        Dict with exchange-specific parameters
    """
    exchange_lower = exchange.lower()
    
    config = {
        'exchange': exchange_lower,
        'fee_config': FEE_OPTIMIZATION_CONFIG.get(exchange_lower, {}),
        'min_position_usd': MULTI_EXCHANGE_CONFIG['min_position_usd'].get(exchange_lower, 5.0),
    }
    
    # Add exchange-specific profit targets
    if exchange_lower == 'coinbase':
        config['stepped_exits'] = STEPPED_PROFIT_CONFIG['coinbase_exit_levels']
    elif exchange_lower == 'kraken':
        config['stepped_exits'] = STEPPED_PROFIT_CONFIG['kraken_exit_levels']
    else:
        config['stepped_exits'] = STEPPED_PROFIT_CONFIG['coinbase_exit_levels']  # Default
    
    return config


# ============================================================================
# VALIDATION
# ============================================================================

def validate_config(config: Dict) -> bool:
    """
    Validate configuration for consistency.
    
    Args:
        config: Configuration dictionary
        
    Returns:
        True if valid, False otherwise
    """
    try:
        # Check scoring weights sum to 100
        if 'scoring_weights' in config:
            total_weight = sum(config['scoring_weights'].values())
            if abs(total_weight - 100) > WEIGHT_TOLERANCE:
                logger.error(f"❌ Scoring weights must sum to 100 (got {total_weight})")
                return False
        
        # Check capital allocation sums to 1.0
        if 'multi_exchange' in config:
            total_allocation = sum(config['multi_exchange']['capital_allocation'].values())
            if abs(total_allocation - 1.0) > ALLOCATION_TOLERANCE:
                logger.error(f"❌ Capital allocation must sum to 1.0 (got {total_allocation})")
                return False
        
        # Check position sizing constraints
        if config.get('min_position_pct', 0) > config.get('max_position_pct', 1):
            logger.error("❌ min_position_pct must be <= max_position_pct")
            return False
        
        logger.info("✅ Configuration validation passed")
        return True
        
    except Exception as e:
        logger.error(f"❌ Configuration validation failed: {e}")
        return False


# ============================================================================
# USAGE
# ============================================================================

if __name__ == "__main__":
    # Example usage
    config = get_profit_optimization_config()
    
    if validate_config(config):
        print("\n✅ Configuration is valid and ready to use")
        print(f"\nKey Settings:")
        print(f"  Enhanced Scoring: {config.get('use_enhanced_scoring')}")
        print(f"  Regime Detection: {config.get('use_regime_detection')}")
        print(f"  Stepped Exits: {config.get('enable_stepped_exits')}")
        print(f"  Min Entry Score: {config.get('min_score_threshold')}/100")
        print(f"  Position Size: {config.get('min_position_pct')*100:.0f}%-{config.get('max_position_pct')*100:.0f}%")
    else:
        print("\n❌ Configuration validation failed")
