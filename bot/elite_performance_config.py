"""
NIJA ELITE PERFORMANCE TARGETS CONFIGURATION
Version: 7.3 (Elite Tier - January 2026)

Implements optimal performance metrics for elite automated trading systems:
- Profit Factor: 2.0 - 2.6 (Elite AI system range)
- Win Rate: 58% - 62% (Optimal balance for profitability)
- Average Loss: -0.4% to -0.7% (Fast compounding, shallow drawdowns)
- Risk:Reward: 1:1.8 - 1:2.5 (Elite range)
- Expectancy: +0.45R to +0.65R per trade (Massive mathematical edge)
- Max Drawdown: <12% (Capital preservation)
- Sharpe Ratio: >1.8 (Risk-adjusted returns)

These targets place NIJA in the top 0.1% of automated trading systems worldwide.

Author: NIJA Trading Systems
Date: January 28, 2026
"""

import logging
from typing import Dict, Tuple

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# CORE PERFORMANCE METRICS - ELITE TARGETS
# ═══════════════════════════════════════════════════════════════════

ELITE_PERFORMANCE_TARGETS = {
    # Profit Factor (Most Important Metric)
    # Total Gross Profit ÷ Total Gross Loss
    'profit_factor': {
        'minimum': 1.5,      # Professional-grade threshold
        'target_min': 2.0,   # Elite AI system floor
        'target_max': 2.6,   # Elite AI system ceiling
        'danger_zone': 3.0,  # Above this may indicate overfitting
        'description': 'Maximizes compounding, controls risk, attracts investors',
    },
    
    # Win Rate (Optimized - NOT Maximized)
    'win_rate': {
        'minimum': 0.50,     # 50% - Below this needs review
        'target_min': 0.58,  # 58% - Elite floor
        'target_max': 0.62,  # 62% - Elite ceiling
        'danger_zone': 0.70, # 70%+ usually indicates martingale or fake edge
        'description': 'Best balance: confidence, profitability, stability',
    },
    
    # Average Loss Per Trade (% of account balance)
    'average_loss_pct': {
        'maximum': -0.008,   # -0.8% - Conservative limit
        'target_min': -0.007,# -0.7% - Elite ceiling
        'target_max': -0.004,# -0.4% - Elite floor (aggressive)
        'description': 'Enables fast compounding, protects longevity, shallow drawdowns',
    },
    
    # Average Win Per Trade (% of account balance)
    'average_win_pct': {
        'minimum': 0.009,    # 0.9% - Minimum for profitability
        'target_min': 0.009, # 0.9% - Elite floor
        'target_max': 0.015, # 1.5% - Elite ceiling
        'optimal': 0.012,    # 1.2% - Sweet spot
        'description': 'Balanced profit targets for sustainable growth',
    },
    
    # Risk:Reward Ratio (R:R)
    'risk_reward_ratio': {
        'minimum': 1.5,      # 1:1.5 - Below this is suboptimal
        'target_min': 1.8,   # 1:1.8 - Elite floor
        'target_max': 2.5,   # 1:2.5 - Elite ceiling
        'optimal': 2.0,      # 1:2.0 - Sweet spot
        'description': 'Enables high win rate + profit factor + rapid growth',
    },
    
    # Expectancy (Real Money Metric)
    # (Win Rate × Avg Win) - (Loss Rate × Avg Loss)
    'expectancy': {
        'minimum': 0.30,     # $0.30 per $1 risked - Professional
        'target_min': 0.45,  # +0.45R - Elite floor
        'target_max': 0.65,  # +0.65R - Elite ceiling
        'optimal': 0.55,     # +0.55R - Sweet spot
        'description': 'Mathematical edge enabling explosive compounding',
    },
    
    # Maximum Drawdown (% of peak equity)
    'max_drawdown': {
        'maximum': 0.15,     # 15% - Hard stop
        'target': 0.12,      # 12% - Elite target
        'optimal': 0.10,     # 10% - Optimal for investor confidence
        'warning': 0.08,     # 8% - Early warning threshold
        'description': 'Capital preservation and investor psychology',
    },
    
    # Sharpe Ratio (Risk-Adjusted Returns)
    'sharpe_ratio': {
        'minimum': 1.2,      # 1.2 - Acceptable
        'target': 1.8,       # 1.8 - Elite target
        'optimal': 2.0,      # 2.0+ - Exceptional
        'description': 'Risk-adjusted return quality',
    },
}


# ═══════════════════════════════════════════════════════════════════
# TRADING FREQUENCY TARGETS
# ═══════════════════════════════════════════════════════════════════

TRADING_FREQUENCY = {
    # Daily trade targets (adaptive based on market conditions)
    'trades_per_day': {
        'minimum': 3,        # At least 3 quality setups
        'target_min': 5,     # 5 trades/day lower bound
        'target_max': 12,    # 12 trades/day upper bound
        'maximum': 20,       # Hard cap (prevents overtrading)
        'description': 'Adaptive frequency for optimal compounding',
    },
    
    # Monthly trade targets
    'trades_per_month': {
        'minimum': 60,       # 3/day × 20 trading days
        'target': 100,       # 5/day × 20 trading days
        'optimal': 150,      # 7.5/day × 20 trading days
        'maximum': 240,      # 12/day × 20 trading days
    },
}


# ═══════════════════════════════════════════════════════════════════
# GROWTH TARGETS (THEORETICAL)
# ═══════════════════════════════════════════════════════════════════

GROWTH_TARGETS = {
    # Monthly growth (theoretical maximum)
    'monthly_growth_theoretical': {
        'calculation': '5 trades/day × 20 days × 0.48% expectancy',
        'value': 0.48,       # 48% monthly theoretical
        'description': 'Maximum possible with perfect execution',
    },
    
    # Monthly growth (realistic target)
    'monthly_growth_target': {
        'conservative': 0.15,  # 15% monthly (throttled)
        'moderate': 0.20,      # 20% monthly (balanced)
        'aggressive': 0.25,    # 25% monthly (elite performance)
        'description': 'Sustainable long-term growth rates',
    },
    
    # Annual growth targets
    'annual_growth_target': {
        'conservative': 4.35,  # 435% (15% monthly compounded)
        'moderate': 7.91,      # 791% (20% monthly compounded)
        'aggressive': 14.55,   # 1455% (25% monthly compounded)
        'description': 'Compounded annual returns',
    },
}


# ═══════════════════════════════════════════════════════════════════
# MULTI-ENGINE AI STACK CONFIGURATION
# ═══════════════════════════════════════════════════════════════════

MULTI_ENGINE_STACK = {
    'enabled': True,
    'description': 'Dynamic rotation between specialized trading engines',
    
    # Engine 1: Momentum Scalping AI
    'momentum_scalping': {
        'enabled': True,
        'priority': 'high',
        'win_rate_target': 0.65,      # 65% - Higher win rate
        'avg_win_target': 0.008,      # 0.8% - Smaller wins
        'avg_loss_target': -0.005,    # -0.5% - Tight stops
        'trade_frequency': 'high',    # 8-12 trades/day
        'market_conditions': ['low_volatility', 'ranging'],
        'description': 'High win rate, fast trades, low drawdown',
    },
    
    # Engine 2: Trend Capture AI
    'trend_capture': {
        'enabled': True,
        'priority': 'high',
        'win_rate_target': 0.50,      # 50% - Lower win rate
        'avg_win_target': 0.025,      # 2.5% - Huge winners
        'avg_loss_target': -0.008,    # -0.8% - Wider stops
        'trade_frequency': 'low',     # 2-4 trades/day
        'market_conditions': ['high_adx', 'trending'],
        'description': 'Lower win rate, huge winners, explosive growth days',
    },
    
    # Engine 3: Volatility Breakout AI
    'volatility_breakout': {
        'enabled': True,
        'priority': 'medium',
        'win_rate_target': 0.55,      # 55% - Moderate win rate
        'avg_win_target': 0.018,      # 1.8% - Large wins
        'avg_loss_target': -0.007,    # -0.7% - Moderate stops
        'trade_frequency': 'medium',  # 3-6 trades/day
        'market_conditions': ['news_events', 'session_open', 'high_volatility'],
        'description': 'News + session surges, largest profit bursts',
    },
    
    # Engine 4: Range Compression AI
    'range_compression': {
        'enabled': True,
        'priority': 'low',
        'win_rate_target': 0.60,      # 60% - Good win rate
        'avg_win_target': 0.006,      # 0.6% - Small consistent wins
        'avg_loss_target': -0.004,    # -0.4% - Very tight stops
        'trade_frequency': 'high',    # 6-10 trades/day
        'market_conditions': ['low_adx', 'ranging', 'consolidation'],
        'description': 'Market-neutral farming, stable profit engine',
    },
}


# ═══════════════════════════════════════════════════════════════════
# POSITION SIZING FOR ELITE METRICS
# ═══════════════════════════════════════════════════════════════════

ELITE_POSITION_SIZING = {
    # Conservative sizing for optimal metrics
    'min_position_pct': 0.02,    # 2% minimum
    'max_position_pct': 0.05,    # 5% maximum
    'optimal_position_pct': 0.03,# 3% optimal
    
    # Total exposure limits
    'max_total_exposure': 0.80,  # 80% max exposure
    'optimal_exposure': 0.60,    # 60% optimal exposure
    
    # Position count limits
    'max_concurrent_positions': 20,  # Up to 20 positions (5% each)
    'optimal_positions': 12,          # 12 positions (balanced)
    'min_positions': 5,               # At least 5 for diversification
}


# ═══════════════════════════════════════════════════════════════════
# STOP LOSS & PROFIT TARGETS FOR ELITE R:R
# ═══════════════════════════════════════════════════════════════════

ELITE_RISK_MANAGEMENT = {
    # Stop Loss Configuration (targeting -0.4% to -0.7% avg loss)
    'stop_loss': {
        'method': 'atr_based',
        'atr_multiplier': 1.5,        # 1.5x ATR for wider stops
        'min_stop_pct': 0.004,        # 0.4% minimum
        'max_stop_pct': 0.007,        # 0.7% maximum
        'optimal_stop_pct': 0.006,    # 0.6% optimal
        'description': 'Wider stops reduce stop-hunts, protect positions',
    },
    
    # Profit Targets (targeting 1:1.8 to 1:2.5 R:R)
    'profit_targets': {
        'method': 'stepped_exits',
        'targets': [
            {
                'name': 'TP1',
                'profit_pct': 0.005,   # 0.5% profit
                'exit_pct': 0.10,      # Exit 10% of position
                'r_multiple': 0.83,    # 0.83R (if stop is 0.6%)
            },
            {
                'name': 'TP2',
                'profit_pct': 0.010,   # 1.0% profit
                'exit_pct': 0.15,      # Exit 15% of position (25% total)
                'r_multiple': 1.67,    # 1.67R
            },
            {
                'name': 'TP3',
                'profit_pct': 0.020,   # 2.0% profit
                'exit_pct': 0.25,      # Exit 25% of position (50% total)
                'r_multiple': 3.33,    # 3.33R
            },
            {
                'name': 'TP4',
                'profit_pct': 0.030,   # 3.0% profit
                'exit_pct': 0.50,      # Exit 50% of position (100% total)
                'r_multiple': 5.0,     # 5.0R
                'action': 'trailing_stop',
            },
        ],
        'use_trailing': True,
        'trailing_activation_r': 2.0,  # Activate trailing at 2R
    },
}


# ═══════════════════════════════════════════════════════════════════
# VALIDATION & MONITORING
# ═══════════════════════════════════════════════════════════════════

PERFORMANCE_VALIDATION = {
    # Check performance every N trades
    'validation_frequency': 20,  # Validate every 20 trades
    
    # Alert thresholds
    'alert_if_below': {
        'profit_factor': 1.8,     # Alert if PF < 1.8
        'win_rate': 0.55,         # Alert if WR < 55%
        'expectancy': 0.40,       # Alert if E < 0.40R
    },
    
    # Auto-adjust if targets missed
    'auto_adjust': {
        'enabled': True,
        'adjustment_interval': 50,  # Adjust every 50 trades
        'max_adjustments': 3,       # Max 3 adjustments per day
    },
}


# ═══════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════

def calculate_expectancy(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """
    Calculate expectancy (expected return per dollar risked)
    
    Formula: (Win Rate × Avg Win) - (Loss Rate × Avg Loss)
    
    Args:
        win_rate: Win rate as decimal (e.g., 0.60 for 60%)
        avg_win: Average win as decimal (e.g., 0.012 for 1.2%)
        avg_loss: Average loss as decimal (e.g., 0.006 for 0.6%)
    
    Returns:
        Expectancy as decimal (e.g., 0.0048 = 0.48% per trade)
    """
    loss_rate = 1.0 - win_rate
    expectancy = (win_rate * avg_win) - (loss_rate * abs(avg_loss))
    return expectancy


def calculate_profit_factor(total_profit: float, total_loss: float) -> float:
    """
    Calculate profit factor (total profit / total loss)
    
    Args:
        total_profit: Total gross profit
        total_loss: Total gross loss (absolute value)
    
    Returns:
        Profit factor (e.g., 2.3)
    """
    if total_loss == 0:
        return float('inf') if total_profit > 0 else 0.0
    return abs(total_profit / total_loss)


def calculate_risk_reward_ratio(avg_win: float, avg_loss: float) -> float:
    """
    Calculate risk:reward ratio
    
    Args:
        avg_win: Average win as decimal (e.g., 0.012)
        avg_loss: Average loss as decimal (e.g., 0.006)
    
    Returns:
        R:R ratio (e.g., 2.0 for 1:2)
    """
    if avg_loss == 0:
        return float('inf') if avg_win > 0 else 0.0
    return abs(avg_win / avg_loss)


def validate_performance_targets(metrics: Dict) -> Tuple[bool, Dict[str, str]]:
    """
    Validate if current performance meets elite targets
    
    Args:
        metrics: Dictionary with performance metrics
            {
                'profit_factor': float,
                'win_rate': float,
                'avg_win_pct': float,
                'avg_loss_pct': float,
                'expectancy': float,
                'max_drawdown': float,
            }
    
    Returns:
        (is_elite, warnings) tuple where:
            is_elite: True if all targets met
            warnings: Dict of metrics that need improvement
    """
    warnings = {}
    
    # Check Profit Factor
    pf = metrics.get('profit_factor', 0)
    pf_target = ELITE_PERFORMANCE_TARGETS['profit_factor']
    if pf < pf_target['target_min']:
        warnings['profit_factor'] = f"Below elite target: {pf:.2f} < {pf_target['target_min']}"
    elif pf > pf_target['danger_zone']:
        warnings['profit_factor'] = f"Overfitting risk: {pf:.2f} > {pf_target['danger_zone']}"
    
    # Check Win Rate
    wr = metrics.get('win_rate', 0)
    wr_target = ELITE_PERFORMANCE_TARGETS['win_rate']
    if wr < wr_target['target_min']:
        warnings['win_rate'] = f"Below elite target: {wr:.1%} < {wr_target['target_min']:.1%}"
    elif wr > wr_target['danger_zone']:
        warnings['win_rate'] = f"Martingale risk: {wr:.1%} > {wr_target['danger_zone']:.1%}"
    
    # Check Expectancy
    exp = metrics.get('expectancy', 0)
    exp_target = ELITE_PERFORMANCE_TARGETS['expectancy']
    if exp < exp_target['target_min']:
        warnings['expectancy'] = f"Below elite target: {exp:.3f}R < {exp_target['target_min']:.3f}R"
    
    # Check Max Drawdown
    dd = metrics.get('max_drawdown', 0)
    dd_target = ELITE_PERFORMANCE_TARGETS['max_drawdown']
    if dd > dd_target['target']:
        warnings['max_drawdown'] = f"Above elite target: {dd:.1%} > {dd_target['target']:.1%}"
    
    is_elite = len(warnings) == 0
    return is_elite, warnings


def get_optimal_position_size(adx: float, signal_quality: float) -> float:
    """
    Calculate optimal position size based on trend strength and signal quality
    
    Args:
        adx: ADX value (trend strength)
        signal_quality: Signal score 0-1 (e.g., 0.8 for 4/5 conditions)
    
    Returns:
        Position size as % of account (e.g., 0.03 for 3%)
    """
    sizing = ELITE_POSITION_SIZING
    
    # Base size on ADX
    if adx < 20:
        base_size = sizing['min_position_pct']  # 2%
    elif adx < 30:
        base_size = sizing['optimal_position_pct']  # 3%
    else:
        base_size = sizing['max_position_pct']  # 5%
    
    # Adjust for signal quality
    quality_multiplier = 0.7 + (0.3 * signal_quality)  # 0.7 - 1.0x
    
    adjusted_size = base_size * quality_multiplier
    
    # Clamp to min/max
    adjusted_size = max(sizing['min_position_pct'], 
                       min(sizing['max_position_pct'], adjusted_size))
    
    return adjusted_size


# ═══════════════════════════════════════════════════════════════════
# EXPORT CONFIGURATION
# ═══════════════════════════════════════════════════════════════════

__all__ = [
    'ELITE_PERFORMANCE_TARGETS',
    'TRADING_FREQUENCY',
    'GROWTH_TARGETS',
    'MULTI_ENGINE_STACK',
    'ELITE_POSITION_SIZING',
    'ELITE_RISK_MANAGEMENT',
    'PERFORMANCE_VALIDATION',
    'calculate_expectancy',
    'calculate_profit_factor',
    'calculate_risk_reward_ratio',
    'validate_performance_targets',
    'get_optimal_position_size',
]


# Log configuration on import
logger.info("✅ NIJA Elite Performance Config v7.3 loaded")
logger.info(f"   Profit Factor Target: {ELITE_PERFORMANCE_TARGETS['profit_factor']['target_min']:.1f} - {ELITE_PERFORMANCE_TARGETS['profit_factor']['target_max']:.1f}")
logger.info(f"   Win Rate Target: {ELITE_PERFORMANCE_TARGETS['win_rate']['target_min']:.0%} - {ELITE_PERFORMANCE_TARGETS['win_rate']['target_max']:.0%}")
logger.info(f"   Expectancy Target: +{ELITE_PERFORMANCE_TARGETS['expectancy']['target_min']:.2f}R - +{ELITE_PERFORMANCE_TARGETS['expectancy']['target_max']:.2f}R")
logger.info(f"   Risk:Reward Target: 1:{ELITE_PERFORMANCE_TARGETS['risk_reward_ratio']['target_min']:.1f} - 1:{ELITE_PERFORMANCE_TARGETS['risk_reward_ratio']['target_max']:.1f}")
