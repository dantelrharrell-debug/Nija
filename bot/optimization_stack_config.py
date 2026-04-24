"""
NIJA Optimization Stack Configuration
=====================================

Configuration file for the optimization algorithms stack.

Author: NIJA Trading Systems
Version: 1.0
Date: January 30, 2026
"""

# Bayesian Optimization Configuration
BAYESIAN_CONFIG = {
    # Parameter search space
    'parameter_bounds': {
        # RSI parameters
        'rsi_oversold': (20.0, 35.0),
        'rsi_overbought': (65.0, 80.0),
        'rsi_period': (9, 21),
        
        # Risk management
        'stop_loss_pct': (0.01, 0.05),
        'take_profit_pct': (0.02, 0.10),
        'trailing_stop_pct': (0.005, 0.03),
        
        # Position sizing
        'position_size_pct': (0.02, 0.10),
        'max_positions': (5, 20),
        
        # Entry timing
        'entry_delay_bars': (0, 5),
        'confirmation_period': (1, 10),
    },
    
    # Optimization settings
    'max_iterations': 50,
    'initial_random_samples': 5,
    'acquisition_function': 'expected_improvement',
    'exploration_weight': 0.1,
}


# Genetic Algorithm Configuration
GENETIC_CONFIG = {
    'population_size': 50,
    'generations': 100,
    'mutation_rate': 0.15,
    'crossover_rate': 0.7,
    'elitism_count': 5,  # Keep top 5 performers
    'tournament_size': 5,
    
    # Fitness function weights
    'fitness_weights': {
        'total_return': 0.30,
        'sharpe_ratio': 0.25,
        'profit_factor': 0.20,
        'win_rate': 0.15,
        'max_drawdown': 0.10,
    },
    
    # Mutation parameters
    'mutation_strength': 0.1,  # % change per mutation
    'adaptive_mutation': True,  # Reduce mutation as generations progress
}


# Reinforcement Learning Configuration
RL_CONFIG = {
    # Q-learning parameters
    'learning_rate': 0.1,
    'discount_factor': 0.95,
    'epsilon': 0.2,  # Exploration rate
    'epsilon_decay': 0.995,
    'epsilon_min': 0.05,
    
    # Experience replay
    'replay_buffer_size': 10000,
    'batch_size': 32,
    'update_frequency': 10,
    
    # State discretization
    'volatility_bins': 5,
    'trend_strength_bins': 5,
    'volume_bins': 3,
    'momentum_bins': 5,
    
    # Reward shaping
    'reward_weights': {
        'profit': 1.0,
        'risk_adjusted_return': 0.5,
        'consistency': 0.3,
    },
}


# Regime Switching Configuration
REGIME_SWITCH_CONFIG = {
    # Regime detection thresholds
    'volatility_spike_threshold': 2.5,  # 2.5x normal = spike
    'drawdown_threshold': 0.05,  # 5% drawdown = defensive
    'correlation_break_threshold': 0.3,  # Correlation < 0.3 = crisis
    'trend_strength_threshold': 0.7,  # ADX-like threshold
    
    # Regime-specific parameter adjustments
    'regime_parameters': {
        'normal': {
            'position_size_multiplier': 1.0,
            'stop_loss_multiplier': 1.0,
            'take_profit_multiplier': 1.0,
            'max_positions': 15,
        },
        'volatile': {
            'position_size_multiplier': 0.5,
            'stop_loss_multiplier': 1.5,
            'take_profit_multiplier': 0.8,
            'max_positions': 10,
        },
        'crisis': {
            'position_size_multiplier': 0.3,
            'stop_loss_multiplier': 2.0,
            'take_profit_multiplier': 0.5,
            'max_positions': 5,
        },
        'defensive': {
            'position_size_multiplier': 0.6,
            'stop_loss_multiplier': 1.2,
            'take_profit_multiplier': 0.9,
            'max_positions': 8,
        },
        'trending': {
            'position_size_multiplier': 1.2,
            'stop_loss_multiplier': 0.9,
            'take_profit_multiplier': 1.3,
            'max_positions': 12,
        },
    },
    
    # Regime persistence (minimum bars before switching)
    'min_regime_duration': 5,
    
    # Emergency override thresholds (immediate switch)
    'emergency_thresholds': {
        'flash_crash_pct': 0.10,  # 10% rapid drop
        'volatility_explosion': 5.0,  # 5x normal volatility
    },
}


# Kalman Filter Configuration
KALMAN_CONFIG = {
    # Filter parameters for different metrics
    'filters': {
        'price': {
            'process_variance': 1e-5,
            'measurement_variance': 1e-2,
        },
        'volatility': {
            'process_variance': 1e-4,
            'measurement_variance': 1e-1,
        },
        'momentum': {
            'process_variance': 1e-3,
            'measurement_variance': 1e-1,
        },
        'rsi': {
            'process_variance': 1e-4,
            'measurement_variance': 5e-2,
        },
        'volume': {
            'process_variance': 1e-3,
            'measurement_variance': 1e-1,
        },
    },
    
    # Adaptive variance (adjust based on regime)
    'adaptive_variance': True,
    'volatile_regime_multiplier': 2.0,  # Increase variance in volatile regimes
}


# Volatility-Adaptive Sizing Configuration
VOLATILITY_SIZING_CONFIG = {
    'base_position_pct': 0.05,  # 5% base position
    'min_position_pct': 0.02,  # 2% minimum
    'max_position_pct': 0.10,  # 10% maximum
    
    # ATR-based volatility thresholds
    'atr_lookback': 20,
    'volatility_thresholds': {
        'extreme_high': 2.5,
        'high': 1.5,
        'normal_upper': 1.2,
        'normal_lower': 0.8,
        'low': 0.8,
        'extreme_low': 0.5,
    },
    
    # Position size multipliers per volatility regime
    'volatility_multipliers': {
        'extreme_high': 0.40,
        'high': 0.65,
        'normal': 1.00,
        'low': 1.25,
        'extreme_low': 1.50,
    },
    
    # Expected gain: +6-10%
    'target_gain_pct': 8.0,
}


# Entry Timing Optimization Configuration
ENTRY_TIMING_CONFIG = {
    # Multi-timeframe confirmation
    'use_multi_timeframe': True,
    'timeframes': ['5m', '15m', '1h'],
    'required_confirmations': 2,
    
    # Technical indicator weights
    'indicator_weights': {
        'rsi': 0.30,
        'macd': 0.25,
        'volume': 0.20,
        'price_action': 0.25,
    },
    
    # Entry delay optimization
    'max_entry_delay_bars': 3,
    'use_limit_orders': True,
    'limit_order_offset_pct': 0.001,  # 0.1% better than market
    
    # Expected gain: +8-15%
    'target_gain_pct': 11.5,
}


# Execution Latency Optimization Configuration
EXECUTION_LATENCY_CONFIG = {
    # Order routing
    'use_smart_routing': True,
    'preferred_order_type': 'limit',  # Prefer maker fees
    'market_order_threshold_urgency': 0.8,  # Use market if urgency > 80%
    
    # Order slicing
    'enable_order_slicing': True,
    'slice_size_threshold': 10000,  # Slice orders > $10k
    'max_slices': 5,
    'slice_delay_ms': 500,
    
    # Fee optimization
    'maker_fee_pct': 0.0004,  # 0.04% maker fee
    'taker_fee_pct': 0.0006,  # 0.06% taker fee
    'fee_savings_threshold': 0.0001,  # Must save > 0.01% to use limit
    
    # Expected gain: +3-7%
    'target_gain_pct': 5.0,
}


# Walk-Forward Optimization Configuration
WALK_FORWARD_CONFIG = {
    'training_window_days': 90,  # 3 months training
    'testing_window_days': 30,  # 1 month testing
    'step_size_days': 30,  # Roll forward 1 month at a time
    
    # Parameter stability tracking
    'track_parameter_stability': True,
    'max_parameter_drift': 0.3,  # Warn if params drift > 30%
    
    # Performance degradation detection
    'performance_degradation_threshold': 0.2,  # Alert if performance drops 20%
    
    # Expected gain: +6-12%
    'target_gain_pct': 9.0,
}


# Portfolio Allocation Configuration
PORTFOLIO_ALLOCATION_CONFIG = {
    # Risk parity principles
    'use_risk_parity': True,
    'target_risk_contribution': 'equal',  # or 'proportional'
    
    # Position limits
    'max_position_weight': 0.20,  # 20% max per position
    'min_position_weight': 0.02,  # 2% minimum
    'target_position_count': 10,
    
    # Correlation-based diversification
    'max_correlation': 0.7,  # Don't add highly correlated positions
    'correlation_lookback': 30,  # Days for correlation calculation
    
    # Rebalancing
    'rebalance_threshold': 0.05,  # Rebalance if weight drifts > 5%
    'rebalance_frequency': 'daily',
    
    # Factor weights for scoring
    'scoring_weights': {
        'profitability': 0.30,
        'trend_strength': 0.20,
        'risk_reward': 0.20,
        'correlation': 0.15,
        'momentum': 0.15,
    },
}


# Performance Target Summary
PERFORMANCE_TARGETS = {
    'volatility_adaptive_sizing': {'min': 6.0, 'target': 8.0, 'max': 10.0},
    'entry_timing_tuning': {'min': 8.0, 'target': 11.5, 'max': 15.0},
    'regime_switching': {'min': 10.0, 'target': 17.5, 'max': 25.0},
    'walk_forward_tuning': {'min': 6.0, 'target': 9.0, 'max': 12.0},
    'execution_latency_tuning': {'min': 3.0, 'target': 5.0, 'max': 7.0},
    
    # Total expected gain
    'total_min': 33.0,
    'total_target': 51.0,
    'total_max': 69.0,
}


# Stack-wide Configuration
OPTIMIZATION_STACK_CONFIG = {
    # Layer activation
    'default_active_layers': ['fast', 'medium', 'emergency', 'stability'],
    'enable_deep_rl': False,  # RL is computationally expensive, enable selectively
    
    # Performance tracking
    'track_performance': True,
    'performance_update_frequency': 100,  # Update metrics every 100 trades
    'save_optimization_history': True,
    'history_file': 'optimization_history.json',
    
    # Layer-specific configs
    'bayesian': BAYESIAN_CONFIG,
    'genetic': GENETIC_CONFIG,
    'reinforcement_learning': RL_CONFIG,
    'regime_switch': REGIME_SWITCH_CONFIG,
    'kalman': KALMAN_CONFIG,
    'volatility_sizing': VOLATILITY_SIZING_CONFIG,
    'entry_timing': ENTRY_TIMING_CONFIG,
    'execution_latency': EXECUTION_LATENCY_CONFIG,
    'walk_forward': WALK_FORWARD_CONFIG,
    'portfolio_allocation': PORTFOLIO_ALLOCATION_CONFIG,
    
    # Performance targets
    'performance_targets': PERFORMANCE_TARGETS,
}


def get_optimization_config(layer: str = None) -> dict:
    """
    Get configuration for a specific layer or the entire stack
    
    Args:
        layer: Layer name ('bayesian', 'genetic', 'rl', etc.) or None for full config
        
    Returns:
        Configuration dictionary
    """
    if layer is None:
        return OPTIMIZATION_STACK_CONFIG
    
    layer_map = {
        'bayesian': BAYESIAN_CONFIG,
        'genetic': GENETIC_CONFIG,
        'rl': RL_CONFIG,
        'reinforcement_learning': RL_CONFIG,
        'regime': REGIME_SWITCH_CONFIG,
        'regime_switch': REGIME_SWITCH_CONFIG,
        'kalman': KALMAN_CONFIG,
        'volatility': VOLATILITY_SIZING_CONFIG,
        'entry': ENTRY_TIMING_CONFIG,
        'execution': EXECUTION_LATENCY_CONFIG,
        'walk_forward': WALK_FORWARD_CONFIG,
        'portfolio': PORTFOLIO_ALLOCATION_CONFIG,
    }
    
    return layer_map.get(layer, OPTIMIZATION_STACK_CONFIG)


if __name__ == "__main__":
    import json
    
    # Print configuration summary
    print("=" * 80)
    print("NIJA OPTIMIZATION STACK CONFIGURATION")
    print("=" * 80)
    
    print("\n📊 Performance Targets:")
    for component, targets in PERFORMANCE_TARGETS.items():
        if component.startswith('total'):
            print(f"\n  {component.upper()}: {targets:.1f}%")
        elif isinstance(targets, dict):
            print(f"  {component}: {targets['min']:.1f}% - {targets['max']:.1f}% (target: {targets['target']:.1f}%)")
    
    print("\n🔧 Active Layers:")
    for layer in OPTIMIZATION_STACK_CONFIG['default_active_layers']:
        print(f"  ✓ {layer}")
    
    print("\n" + "=" * 80)
