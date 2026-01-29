"""
MMIN Configuration
==================

Configuration for Multi-Market Intelligence Network
"""

# Market Categories
MARKET_CATEGORIES = {
    'crypto': {
        'symbols': ['BTC-USD', 'ETH-USD', 'SOL-USD', 'AVAX-USD', 'MATIC-USD'],
        'exchanges': ['coinbase', 'kraken', 'binance'],
        'update_frequency': 60,  # seconds
    },
    'forex': {
        'symbols': ['EUR/USD', 'GBP/USD', 'USD/JPY', 'AUD/USD', 'USD/CHF'],
        'exchanges': ['oanda', 'alpaca'],
        'update_frequency': 60,
    },
    'equities': {
        'symbols': ['SPY', 'QQQ', 'IWM', 'AAPL', 'MSFT', 'NVDA', 'TSLA'],
        'exchanges': ['alpaca'],
        'update_frequency': 60,
    },
    'commodities': {
        'symbols': ['GLD', 'SLV', 'USO', 'DBA'],
        'exchanges': ['alpaca'],
        'update_frequency': 300,  # 5 minutes
    },
    'bonds': {
        'symbols': ['TLT', 'IEF', 'SHY'],
        'exchanges': ['alpaca'],
        'update_frequency': 300,
    }
}

# Cross-Market Correlation Settings
CORRELATION_CONFIG = {
    'window_sizes': [20, 50, 100, 200],  # Rolling correlation windows in periods
    'min_correlation_threshold': 0.7,  # Minimum correlation to consider significant
    'update_frequency': 300,  # Update correlations every 5 minutes
    'lookback_periods': 500,  # Historical data points for correlation calculation
}

# Macro Regime Detection
MACRO_REGIME_CONFIG = {
    'regimes': [
        'risk_on',      # High equity vol, crypto rising, bonds falling
        'risk_off',     # Flight to safety, bonds rising, crypto/equities falling
        'inflation',    # Commodities rising, bonds falling
        'deflation',    # Commodities falling, bonds rising
        'growth',       # Equities and crypto rising together
        'recession',    # Everything falling except bonds/USD
    ],
    'indicators': {
        'vix_threshold': 20,  # VIX above = risk off
        'dxy_threshold': 100,  # Dollar index
        'bond_yield_threshold': 0.04,  # 4% threshold
    },
    'detection_window': 20,  # Periods for regime detection
    'min_regime_duration': 5,  # Minimum periods before regime change
}

# Transfer Learning Configuration
TRANSFER_LEARNING_CONFIG = {
    'enabled': True,
    'source_markets': ['crypto', 'equities'],  # Learn from these first
    'target_markets': ['forex', 'commodities'],  # Apply learnings here
    'feature_dimension': 50,  # Embedding dimension for features
    'pattern_types': [
        'breakout',
        'reversal',
        'trend_continuation',
        'range_bound',
        'volatility_expansion',
        'volatility_contraction',
    ],
    'learning_rate': 0.001,
    'batch_size': 32,
    'epochs': 100,
}

# Global Capital Allocation
CAPITAL_ALLOCATION_CONFIG = {
    'enabled': True,
    'rebalance_frequency': 3600,  # Rebalance every hour
    'min_allocation_per_market': 0.05,  # Minimum 5% per market
    'max_allocation_per_market': 0.50,  # Maximum 50% per market
    'allocation_strategy': 'adaptive',  # 'fixed', 'adaptive', 'aggressive'

    # Adaptive allocation based on metrics
    'allocation_metrics': {
        'sharpe_ratio_weight': 0.3,
        'win_rate_weight': 0.2,
        'profit_factor_weight': 0.2,
        'opportunity_count_weight': 0.15,
        'correlation_diversity_weight': 0.15,
    },

    # Fixed allocation (if strategy = 'fixed')
    'fixed_allocation': {
        'crypto': 0.40,
        'equities': 0.30,
        'forex': 0.15,
        'commodities': 0.10,
        'bonds': 0.05,
    },
}

# Pattern Recognition Settings
PATTERN_RECOGNITION_CONFIG = {
    'enabled': True,
    'min_pattern_confidence': 0.65,
    'pattern_lookback': 100,  # Bars to analyze for patterns
    'cross_market_validation': True,  # Require confirmation from correlated markets
    'pattern_types': {
        'technical': ['head_shoulders', 'double_top', 'triangle', 'channel'],
        'volume': ['volume_surge', 'volume_dry_up', 'accumulation', 'distribution'],
        'momentum': ['divergence', 'convergence', 'breakout', 'breakdown'],
    },
}

# MMIN Engine Settings
MMIN_ENGINE_CONFIG = {
    'enabled': True,
    'mode': 'adaptive',  # 'conservative', 'balanced', 'adaptive', 'aggressive'
    'min_markets_active': 2,  # Minimum markets to trade across
    'max_markets_active': 5,  # Maximum concurrent markets
    'cross_market_signals_required': 2,  # Require confirmation from N markets
    'intelligence_level': 'god_mode',  # 'basic', 'advanced', 'god_mode'

    # Performance thresholds
    'performance_thresholds': {
        'min_sharpe_ratio': 1.5,
        'min_win_rate': 0.55,
        'min_profit_factor': 1.8,
        'max_drawdown': 0.15,
    },

    # Update frequencies
    'correlation_update_interval': 300,  # 5 minutes
    'regime_update_interval': 600,  # 10 minutes
    'allocation_update_interval': 3600,  # 1 hour
    'pattern_scan_interval': 60,  # 1 minute
}

# Feature Extraction for Transfer Learning
FEATURE_EXTRACTION_CONFIG = {
    'price_features': [
        'returns',
        'log_returns',
        'realized_volatility',
        'high_low_range',
        'close_open_delta',
    ],
    'technical_features': [
        'rsi_9',
        'rsi_14',
        'macd',
        'macd_signal',
        'macd_histogram',
        'bb_upper',
        'bb_lower',
        'bb_width',
        'atr_14',
        'adx_14',
    ],
    'volume_features': [
        'volume',
        'volume_ma_20',
        'volume_ratio',
        'obv',
        'vwap_distance',
    ],
    'market_structure': [
        'higher_highs',
        'higher_lows',
        'lower_highs',
        'lower_lows',
        'trend_strength',
    ],
    'normalization': 'standardize',  # 'standardize', 'minmax', 'robust'
}

# Opportunity Scoring
OPPORTUNITY_SCORING_CONFIG = {
    'scoring_factors': {
        'technical_setup': 0.25,
        'regime_alignment': 0.20,
        'correlation_support': 0.20,
        'volume_profile': 0.15,
        'risk_reward_ratio': 0.20,
    },
    'min_score_threshold': 0.65,  # Minimum score to consider opportunity
    'max_opportunities_per_market': 10,
    'opportunity_expiry': 3600,  # Opportunities expire after 1 hour
}
