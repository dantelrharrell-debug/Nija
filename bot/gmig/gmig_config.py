"""
GMIG Configuration
==================

Configuration for Global Macro Intelligence Grid components.
"""

from typing import Dict, List

# GMIG Engine Configuration
GMIG_ENGINE_CONFIG = {
    'enabled': True,
    'mode': 'full',  # 'full', 'essential', 'crisis_only'
    'intelligence_level': 'ultra',  # 'standard', 'advanced', 'ultra'
    'update_frequency_minutes': 15,
    'crisis_check_frequency_minutes': 5,
}

# Central Bank Configuration
CENTRAL_BANK_CONFIG = {
    'tracked_banks': [
        'FED',      # US Federal Reserve
        'ECB',      # European Central Bank
        'BOJ',      # Bank of Japan
        'BOE',      # Bank of England
        'PBOC',     # People's Bank of China
        'SNB',      # Swiss National Bank
        'BOC',      # Bank of Canada
        'RBA',      # Reserve Bank of Australia
    ],
    'meeting_lookback_days': 90,
    'forward_guidance_window_days': 180,
    'policy_impact_weight': {
        'FED': 1.0,     # Highest global impact
        'ECB': 0.8,
        'BOJ': 0.7,
        'BOE': 0.6,
        'PBOC': 0.9,    # High impact on crypto/risk assets
        'SNB': 0.4,
        'BOC': 0.5,
        'RBA': 0.5,
    }
}

# Interest Rate Futures Configuration
INTEREST_RATE_FUTURES_CONFIG = {
    'tracked_instruments': [
        'ZQ',   # 30-Day Fed Funds Futures
        'ZT',   # 2-Year Treasury Note Futures
        'ZF',   # 5-Year Treasury Note Futures
        'ZN',   # 10-Year Treasury Note Futures
        'ZB',   # 30-Year Treasury Bond Futures
        'SR3',  # 3-Month SOFR Futures
    ],
    'probability_threshold': 0.25,  # Minimum probability to consider
    'rate_change_threshold': 0.25,   # 25 bps minimum change to signal
    'forward_periods': 12,           # Look ahead 12 months
}

# Yield Curve Configuration
YIELD_CURVE_CONFIG = {
    'tenors': ['1M', '3M', '6M', '1Y', '2Y', '3Y', '5Y', '7Y', '10Y', '20Y', '30Y'],
    'inversion_threshold': -0.10,    # 10 bps inversion triggers signal
    'steepening_threshold': 0.50,    # 50 bps steepening is significant
    'recession_probability_threshold': 0.35,  # 35% probability triggers warning
    'historical_lookback_years': 30,
    'ai_model_features': [
        'slope_2y_10y',
        'slope_3m_10y',
        'slope_5y_30y',
        'curvature',
        'level',
        'volatility',
        'fed_funds_rate',
        'inflation_expectation',
    ]
}

# Liquidity Stress Configuration
LIQUIDITY_STRESS_CONFIG = {
    'metrics': {
        'ted_spread': {
            'normal': 0.50,      # Below 50 bps is normal
            'elevated': 1.00,    # Above 100 bps is elevated
            'crisis': 2.00,      # Above 200 bps is crisis
        },
        'libor_ois_spread': {
            'normal': 0.10,
            'elevated': 0.25,
            'crisis': 0.50,
        },
        'vix': {
            'normal': 20,
            'elevated': 30,
            'crisis': 40,
        },
        'move_index': {  # Bond market volatility
            'normal': 100,
            'elevated': 130,
            'crisis': 160,
        },
        'high_yield_spread': {
            'normal': 4.00,      # 400 bps spread
            'elevated': 6.00,    # 600 bps spread
            'crisis': 10.00,     # 1000 bps spread
        },
    },
    'repo_markets': ['overnight', 'term'],
    'stress_score_threshold': {
        'green': 0.3,
        'yellow': 0.5,
        'orange': 0.7,
        'red': 0.9,
    }
}

# Crisis Warning Configuration
CRISIS_WARNING_CONFIG = {
    'alert_levels': {
        'green': {
            'threshold': 0.2,
            'description': 'Normal market conditions',
            'action': 'standard_operation',
        },
        'yellow': {
            'threshold': 0.4,
            'description': 'Elevated risk, monitor closely',
            'action': 'increase_monitoring',
        },
        'orange': {
            'threshold': 0.6,
            'description': 'High risk, reduce exposure',
            'action': 'reduce_positions',
        },
        'red': {
            'threshold': 0.8,
            'description': 'Crisis imminent, defensive positioning',
            'action': 'emergency_defensive',
        },
    },
    'indicators': [
        'yield_curve_inversion',
        'liquidity_stress',
        'central_bank_emergency_action',
        'credit_spread_blowout',
        'equity_volatility_spike',
        'cross_asset_correlation_breakdown',
        'repo_market_stress',
        'currency_volatility',
    ],
    'crisis_patterns': {
        '2008_financial': {
            'ted_spread': 4.0,
            'vix': 80,
            'yield_curve': -0.50,
            'credit_spread': 20.0,
        },
        '2020_covid': {
            'ted_spread': 1.5,
            'vix': 85,
            'yield_curve': 0.0,
            'credit_spread': 10.0,
        },
        '2011_eurozone': {
            'ted_spread': 1.0,
            'vix': 45,
            'yield_curve': 0.0,
            'credit_spread': 8.0,
        },
    },
    'confidence_threshold': 0.75,  # 75% confidence to trigger alert
}

# Fund-Grade Deployment Configuration
FUND_GRADE_CONFIG = {
    'reporting': {
        'frequency': 'daily',
        'formats': ['pdf', 'excel', 'json'],
        'include_attribution': True,
        'include_risk_metrics': True,
        'include_macro_context': True,
    },
    'multi_account': {
        'orchestration_mode': 'centralized',  # or 'distributed'
        'capital_allocation_method': 'risk_parity',  # 'equal_weight', 'kelly', 'risk_parity'
        'rebalance_frequency_hours': 24,
        'max_accounts': 1000,
    },
    'governance': {
        'auto_rebalance': True,
        'auto_risk_reduction': True,
        'emergency_stop_enabled': True,
        'compliance_checks_enabled': True,
        'audit_trail_retention_days': 365 * 7,  # 7 years
    }
}

# Data Sources Configuration
DATA_SOURCES_CONFIG = {
    'fred': {  # Federal Reserve Economic Data
        'enabled': True,
        'api_key_env': 'FRED_API_KEY',
        'rate_limit_per_day': 10000,
    },
    'bloomberg': {
        'enabled': False,  # Requires Bloomberg Terminal subscription
        'use_open_data': True,  # Use publicly available Bloomberg data
    },
    'treasury_direct': {
        'enabled': True,
        'url': 'https://www.treasurydirect.gov/GA-FI/FedInvest/selectSecurityPriceDate.htm',
    },
    'cme': {  # CME Group for futures data
        'enabled': True,
        'use_market_data': True,
    }
}
