"""
Meta-AI Evolution Engine Configuration
========================================

Configuration parameters for genetic evolution, RL strategy selection,
swarm intelligence, and alpha discovery.
"""

# Genetic Algorithm Configuration
GENETIC_CONFIG = {
    'enabled': True,
    'population_size': 50,  # Number of strategy variants in population
    'generations': 100,  # Number of evolution iterations
    'mutation_rate': 0.15,  # Probability of parameter mutation (15%)
    'crossover_rate': 0.7,  # Probability of crossover (70%)
    'elite_percentage': 0.1,  # Top 10% preserved each generation
    'tournament_size': 5,  # Tournament selection size
    'fitness_window': 30,  # Days to evaluate fitness
    'min_trades': 10,  # Minimum trades for valid fitness evaluation
}

# Reinforcement Learning Configuration
RL_CONFIG = {
    'enabled': True,
    'learning_rate': 0.001,  # Q-learning rate
    'discount_factor': 0.95,  # Future reward discount (gamma)
    'exploration_rate': 0.2,  # Initial exploration rate (epsilon)
    'exploration_decay': 0.995,  # Epsilon decay per episode
    'min_exploration': 0.05,  # Minimum exploration rate
    'replay_buffer_size': 10000,  # Experience replay buffer
    'batch_size': 32,  # Training batch size
    'update_frequency': 100,  # Update target network every N steps
    'reward_scaling': 1.0,  # Scale rewards for stability
}

# Strategy Swarm Configuration
SWARM_CONFIG = {
    'enabled': True,
    'num_strategies': 10,  # Number of strategies in swarm
    'diversity_threshold': 0.3,  # Minimum diversity between strategies
    'performance_window': 7,  # Days for performance evaluation
    'rebalance_frequency': 24,  # Hours between swarm rebalancing
    'min_allocation': 0.05,  # Minimum capital allocation per strategy (5%)
    'max_allocation': 0.30,  # Maximum capital allocation per strategy (30%)
    'correlation_threshold': 0.7,  # Maximum correlation between strategies
}

# Strategy Breeder Configuration
BREEDER_CONFIG = {
    'enabled': True,
    'breeding_frequency': 7,  # Days between breeding cycles
    'parent_selection_top_n': 5,  # Top N strategies for breeding
    'offspring_per_generation': 10,  # New strategies per cycle
    'hybrid_probability': 0.5,  # Chance of hybrid vs mutation
    'trait_inheritance_rate': 0.7,  # Probability of inheriting parent trait
    'min_performance_percentile': 0.6,  # 60th percentile minimum for breeding
}

# Alpha Discovery Configuration
ALPHA_CONFIG = {
    'enabled': True,
    'scan_frequency': 12,  # Hours between alpha scans
    'indicator_combinations': 100,  # Random combinations to test
    'min_sharpe': 1.5,  # Minimum Sharpe ratio for alpha signal
    'min_win_rate': 0.55,  # Minimum win rate (55%)
    'max_drawdown': 0.15,  # Maximum acceptable drawdown (15%)
    'backtest_period': 90,  # Days for alpha validation
    'correlation_check': True,  # Check correlation with existing alphas
    'max_correlation': 0.6,  # Maximum correlation with existing signals
}

# Evolution Engine Configuration
EVOLUTION_ENGINE_CONFIG = {
    'enabled': True,
    'mode': 'adaptive',  # 'genetic', 'rl', 'swarm', 'adaptive' (all)
    'evaluation_frequency': 24,  # Hours between evolution cycles
    'performance_metrics': [
        'sharpe_ratio',
        'profit_factor',
        'win_rate',
        'max_drawdown',
        'expectancy',
        'sortino_ratio',
    ],
    'fitness_weights': {
        'sharpe_ratio': 0.25,
        'profit_factor': 0.20,
        'win_rate': 0.15,
        'max_drawdown': 0.15,
        'expectancy': 0.15,
        'sortino_ratio': 0.10,
    },
    'auto_deploy_threshold': 0.80,  # Auto-deploy if fitness > 80th percentile
    'safety_checks': True,  # Enable safety validation before deployment
    'max_concurrent_strategies': 20,  # Maximum active strategies
    'min_strategy_age_days': 7,  # Minimum age before retirement
}

# Strategy Parameter Search Space
# These define the ranges for genetic evolution and breeding
PARAMETER_SEARCH_SPACE = {
    'rsi_period': (5, 21),  # RSI period range
    'rsi_oversold': (20, 40),  # RSI oversold threshold
    'rsi_overbought': (60, 80),  # RSI overbought threshold
    'ema_fast': (5, 15),  # Fast EMA period
    'ema_medium': (15, 30),  # Medium EMA period
    'ema_slow': (30, 70),  # Slow EMA period
    'adx_threshold': (15, 30),  # ADX minimum for trend
    'atr_multiplier': (0.5, 3.0),  # ATR stop loss multiplier
    'position_size_min': (0.02, 0.05),  # Min position size (2-5%)
    'position_size_max': (0.05, 0.15),  # Max position size (5-15%)
    'take_profit_pct': (0.005, 0.03),  # Take profit (0.5-3%)
    'stop_loss_pct': (0.003, 0.015),  # Stop loss (0.3-1.5%)
    'volume_threshold': (0.5, 2.0),  # Volume multiplier
    'macd_fast': (8, 16),  # MACD fast period
    'macd_slow': (21, 35),  # MACD slow period
    'macd_signal': (7, 12),  # MACD signal period
}

# Performance Thresholds for Strategy Survival
SURVIVAL_THRESHOLDS = {
    'min_sharpe_ratio': 0.8,  # Minimum Sharpe ratio
    'min_profit_factor': 1.2,  # Minimum profit factor
    'min_win_rate': 0.45,  # Minimum win rate (45%)
    'max_drawdown': 0.20,  # Maximum drawdown (20%)
    'min_trades': 20,  # Minimum number of trades
    'min_expectancy': 0.1,  # Minimum expectancy (R-multiple)
}
