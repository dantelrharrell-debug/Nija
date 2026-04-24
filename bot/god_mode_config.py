"""
NIJA God Mode Configuration
============================

Configuration settings for all God Mode features.

Author: NIJA Trading Systems
Version: 1.0 - God Mode Edition
Date: January 29, 2026
"""

# 1️⃣ Bayesian Regime Probability Engine Configuration
BAYESIAN_REGIME_CONFIG = {
    # Prior probabilities (will be updated based on observed data)
    'prior_trending': 0.33,
    'prior_ranging': 0.33,
    'prior_volatile': 0.34,
    
    # Regime detection thresholds
    'trending_adx_min': 25.0,
    'ranging_adx_max': 20.0,
    'volatile_atr_threshold': 0.03,  # 3% ATR/price
    
    # Learning parameters
    'history_size': 1000,  # Number of regime observations to track
    'prior_update_rate': 0.20,  # Blend rate for prior updates (20% new, 80% old)
    'transition_threshold': 0.20,  # Minimum probability change to signal transition
}

# 2️⃣ Meta-Learning Optimizer Configuration
META_OPTIMIZER_CONFIG = {
    # Learning rates
    'learning_rate': 0.10,
    'exploration_rate': 0.20,
    
    # Confidence and decay
    'min_confidence': 0.30,  # Minimum confidence to use parameters
    'exploration_decay': 0.95,  # Decay exploration over time
    'learning_rate_decay': 0.98,
    
    # Ensemble settings
    'ensemble_size': 5,  # Top N parameter sets to ensemble
}

# 3️⃣ Walk-Forward Optimization Configuration
WALK_FORWARD_CONFIG = {
    # Window sizes
    'train_window_days': 90,  # 3 months training
    'test_window_days': 30,   # 1 month testing
    'step_days': 30,          # 1 month step forward
    
    # Optimization settings
    'generations': 20,  # Genetic algorithm generations per window
    'efficiency_threshold': 0.70,  # Test/train performance ratio threshold
    
    # Genetic algorithm config
    'genetic_config': {
        'population_size': 20,
        'generations': 20,
        'mutation_rate': 0.15,
        'crossover_rate': 0.70,
        'elitism_count': 2,
    },
    
    # Stability tracking
    'stability_lookback': 5,  # Windows to analyze for stability
}

# 4️⃣ Risk Parity & Correlation Control Configuration
RISK_PARITY_CONFIG = {
    # Risk targets
    'target_portfolio_vol': 0.15,  # 15% annual volatility target
    'rebalance_threshold': 0.05,   # 5% deviation triggers rebalance
    
    # Position limits
    'min_position_size': 0.01,  # 1% minimum
    'max_position_size': 0.20,  # 20% maximum
    
    # Volatility calculation
    'vol_lookback_days': 30,
    
    # Correlation settings
    'use_correlation_adjustment': True,
    'correlation_floor': 0.3,  # Minimum correlation to assume
    
    # Advanced features
    'use_hierarchical': False,  # Hierarchical risk budgeting
    'asset_class_budgets': {},  # Optional: specific budgets by asset class
}

# 5️⃣ Live Reinforcement Learning Configuration
LIVE_RL_CONFIG = {
    # Q-learning parameters
    'rl_config': {
        'learning_rate': 0.10,
        'discount_factor': 0.95,
        'epsilon': 0.20,  # Initial exploration rate
        'epsilon_decay': 0.995,
        'epsilon_min': 0.05,
        'replay_buffer_size': 1000,
    },
    
    # Reward calculation
    'reward_scale': 1.0,
    'penalty_per_day': 0.001,  # Small penalty for holding time
    'min_reward': -1.0,
    'max_reward': 1.0,
    
    # Learning frequency
    'update_frequency': 1,  # Update after every N trades
    'batch_size': 10,
}

# 🔥 God Mode Master Configuration
GOD_MODE_CONFIG = {
    # Feature toggles (enable/disable individual components)
    'enable_bayesian_regime': True,
    'enable_meta_optimizer': True,
    'enable_walk_forward': True,
    'enable_risk_parity': True,
    'enable_live_rl': True,
    
    # Sub-system configurations
    'bayesian_config': BAYESIAN_REGIME_CONFIG,
    'meta_optimizer_config': META_OPTIMIZER_CONFIG,
    'walk_forward_config': WALK_FORWARD_CONFIG,
    'risk_parity_config': RISK_PARITY_CONFIG,
    'live_rl_config': LIVE_RL_CONFIG,
    
    # Integration settings
    'use_regime_weighted_params': True,  # Use Bayesian regime probabilities to weight parameters
    'use_ensemble_params': True,         # Use ensemble of top parameters
    'rebalance_frequency_hours': 24,     # How often to rebalance portfolio
    
    # State persistence
    'state_dir': './god_mode_state',
    'auto_save': True,
    'save_frequency_trades': 10,  # Save state every N trades
}

# Performance targets for God Mode
GOD_MODE_TARGETS = {
    'target_sharpe_ratio': 2.5,
    'target_win_rate': 0.65,
    'target_profit_factor': 2.0,
    'max_drawdown': 0.15,
    'min_trades_per_day': 5,
}

# Conservative God Mode (for smaller accounts or cautious traders)
CONSERVATIVE_GOD_MODE_CONFIG = GOD_MODE_CONFIG.copy()
CONSERVATIVE_GOD_MODE_CONFIG.update({
    'meta_optimizer_config': {
        **META_OPTIMIZER_CONFIG,
        'exploration_rate': 0.10,  # Less exploration
    },
    'risk_parity_config': {
        **RISK_PARITY_CONFIG,
        'target_portfolio_vol': 0.10,  # Lower volatility target
        'max_position_size': 0.10,     # Smaller max positions
    },
})

# Aggressive God Mode (for larger accounts with higher risk tolerance)
AGGRESSIVE_GOD_MODE_CONFIG = GOD_MODE_CONFIG.copy()
AGGRESSIVE_GOD_MODE_CONFIG.update({
    'meta_optimizer_config': {
        **META_OPTIMIZER_CONFIG,
        'exploration_rate': 0.30,  # More exploration
    },
    'risk_parity_config': {
        **RISK_PARITY_CONFIG,
        'target_portfolio_vol': 0.25,  # Higher volatility target
        'max_position_size': 0.30,     # Larger max positions
    },
})
