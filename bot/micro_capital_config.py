"""
NIJA Micro Capital Mode Configuration
======================================

Configuration for micro capital accounts ($15-$500) with:
- Optimized for small capital fast-frequency trading (Pro-Level)
- Dynamic position scaling based on equity
- Multi-broker support (Coinbase + Kraken)
- Advanced signal filtering and AI trade validation
- Automatic feature enablement as capital grows

Optimized for:
- Small capital fast-frequency trading
- Pro-Level position sizing (22% max per position)
- Higher position count (5 concurrent positions)
- Tight risk management (0.7% risk per trade)
- Gradual scaling with account growth

Author: NIJA Trading Systems
Version: 2.0
Date: January 30, 2026
Updated: Pro-Level Optimization for small capital fast-frequency
"""

import os
import logging
from typing import Dict, Optional

logger = logging.getLogger("nija.micro_capital_config")

# ============================================================================
# OPERATIONAL MODE
# ============================================================================

MICRO_CAPITAL_MODE = True

# Trading mode configuration
MODE = "MASTER_ONLY"  # Only master account trades (no copy trading initially)

# Broker configuration
PRIMARY_BROKER = "COINBASE"
SECONDARY_BROKER = "KRAKEN"

# Live trading settings
LIVE_TRADING = True
PRO_MODE = True

# Copy trading (disabled until >= $500, managed by dynamic scaling)
COPY_TRADING = False  # Auto-enabled when BASE_CAPITAL >= $500

# ============================================================================
# BALANCE AND TRADE SIZE REQUIREMENTS
# ============================================================================

MIN_BALANCE_TO_TRADE = 15.00  # Minimum account balance to start trading
MIN_TRADE_SIZE = 5.00  # Minimum trade size in USD

# ============================================================================
# POSITION MANAGEMENT
# ============================================================================

# Pro-Level Optimization (Jan 30, 2026):
# - MAX_POSITIONS = 4: Balanced diversification for small capital
# - MAX_POSITION_PCT = 25%: Larger individual positions for small capital efficiency
# - RISK_PER_TRADE = 0.9%: Balanced risk control per trade
#
# NOTE: While MAX_POSITIONS × MAX_POSITION_PCT = 100% theoretical maximum,
# the risk_manager.py enforces max_total_exposure = 60% as a safeguard.
# This configuration is optimized for fast-frequency trading where not all
# positions will be at maximum size simultaneously.

MAX_POSITIONS = 4  # Maximum concurrent positions (UPDATED Jan 30, 2026 for fast-frequency trading)

# Position sizing as percentage of capital
MAX_POSITION_PCT = 25.0  # Maximum 25% of capital per position (OPTIMIZED for small capital fast-frequency)
RISK_PER_TRADE = 0.9  # Risk 0.9% per trade (OPTIMIZED for Pro-Level performance)

# ============================================================================
# RISK MANAGEMENT
# ============================================================================

DAILY_MAX_LOSS = 6.0  # Maximum 6% daily loss
MAX_DRAWDOWN = 12.0  # Maximum 12% drawdown before stopping

# Position sizer configuration
POSITION_SIZER = "HYBRID"

# Hybrid position sizing weights
KELLY_WEIGHT = 0.30
VOLATILITY_WEIGHT = 0.40
EQUITY_WEIGHT = 0.30

# ============================================================================
# SIGNAL FILTERING
# ============================================================================

MIN_SIGNAL_SCORE = 0.75  # Minimum signal quality score (75%)
MIN_AI_CONFIDENCE = 0.70  # Minimum AI confidence level (70%)
MIN_RISK_REWARD = 1.8  # Minimum risk/reward ratio

# ============================================================================
# TRADING PAIRS
# ============================================================================

TRADE_ONLY = ["BTC", "ETH", "SOL"]  # Only trade these major cryptocurrencies

# ============================================================================
# ADVANCED FEATURES
# ============================================================================

MARKET_REGIME_ENGINE = True  # Enable market regime detection
SIGNAL_ENSEMBLE = True  # Use ensemble of signals
AI_TRADE_FILTER = True  # Enable AI-based trade filtering

# ============================================================================
# LEVERAGE AND ARBITRAGE
# ============================================================================

LEVERAGE_ENABLED = False  # No leverage initially (enabled at $1000+)
ARBITRAGE = False  # Arbitrage disabled

# ============================================================================
# SAFETY AND ERROR HANDLING
# ============================================================================

AUTO_SHUTOFF_ON_ERRORS = True  # Auto-shutoff on consecutive errors
MAX_CONSECUTIVE_LOSSES = 3  # Maximum consecutive losses before pause

# ============================================================================
# CAPITAL ALLOCATION
# ============================================================================

FORCE_CASH_BUFFER = 15.0  # Keep 15% of capital unallocated

# ============================================================================
# EXCHANGE PRIORITY
# ============================================================================

EXCHANGE_PRIORITY = ["COINBASE", "KRAKEN"]

# Minimum balances per exchange
MIN_BALANCE_KRAKEN = 50.0
MIN_BALANCE_COINBASE = 10.0

# ============================================================================
# DYNAMIC SCALING BASED ON EQUITY
# ============================================================================

def get_dynamic_config(equity: float) -> Dict:
    """
    Get configuration that scales dynamically based on account equity.
    
    Args:
        equity: Current account equity/balance
        
    Returns:
        Dict with dynamically adjusted configuration values
    """
    config = {
        'max_positions': MAX_POSITIONS,
        'risk_per_trade': RISK_PER_TRADE,
        'copy_trading': COPY_TRADING,
        'leverage_enabled': LEVERAGE_ENABLED,
    }
    
    # Scaling at $250
    if equity >= 250:
        config['max_positions'] = 3
        config['risk_per_trade'] = 4.0
        logger.info(f"Equity ${equity:.2f}: Scaled to 3 positions, 4% risk per trade")
    
    # Scaling at $500
    if equity >= 500:
        config['max_positions'] = 4
        config['copy_trading'] = True
        logger.info(f"Equity ${equity:.2f}: Scaled to 4 positions, copy trading enabled")
    
    # Scaling at $1000
    if equity >= 1000:
        config['max_positions'] = 6
        config['risk_per_trade'] = 5.0
        config['leverage_enabled'] = True
        logger.info(f"Equity ${equity:.2f}: Scaled to 6 positions, 5% risk, leverage enabled")
    
    return config

# ============================================================================
# LOGGING AND DIAGNOSTICS
# ============================================================================

LOG_SIGNAL_REJECTIONS = True  # Log why signals were rejected
LOG_ENTRY_BLOCK_REASONS = True  # Log why entries were blocked

# ============================================================================
# STATE MANAGEMENT
# ============================================================================

RESET_STRATEGY_STATE = True  # Reset strategy state on startup
CLEAR_ENTRY_BLOCKS = True  # Clear entry blocks on startup
FLUSH_CACHED_BALANCES = True  # Flush cached balances on startup

# ============================================================================
# COMPLETE CONFIGURATION DICTIONARY
# ============================================================================

MICRO_CAPITAL_CONFIG = {
    # Operational mode
    'micro_capital_mode': MICRO_CAPITAL_MODE,
    'mode': MODE,
    'primary_broker': PRIMARY_BROKER,
    'secondary_broker': SECONDARY_BROKER,
    
    # Trading settings
    'live_trading': LIVE_TRADING,
    'pro_mode': PRO_MODE,
    'copy_trading': COPY_TRADING,
    
    # Balance requirements
    'min_balance_to_trade': MIN_BALANCE_TO_TRADE,
    'min_trade_size': MIN_TRADE_SIZE,
    
    # Position management
    'max_positions': MAX_POSITIONS,
    'max_position_pct': MAX_POSITION_PCT,
    'risk_per_trade': RISK_PER_TRADE,
    
    # Risk management
    'daily_max_loss': DAILY_MAX_LOSS,
    'max_drawdown': MAX_DRAWDOWN,
    'position_sizer': POSITION_SIZER,
    'kelly_weight': KELLY_WEIGHT,
    'volatility_weight': VOLATILITY_WEIGHT,
    'equity_weight': EQUITY_WEIGHT,
    
    # Signal filtering
    'min_signal_score': MIN_SIGNAL_SCORE,
    'min_ai_confidence': MIN_AI_CONFIDENCE,
    'min_risk_reward': MIN_RISK_REWARD,
    
    # Trading pairs
    'trade_only': TRADE_ONLY,
    
    # Advanced features
    'market_regime_engine': MARKET_REGIME_ENGINE,
    'signal_ensemble': SIGNAL_ENSEMBLE,
    'ai_trade_filter': AI_TRADE_FILTER,
    
    # Leverage and arbitrage
    'leverage_enabled': LEVERAGE_ENABLED,
    'arbitrage': ARBITRAGE,
    
    # Safety
    'auto_shutoff_on_errors': AUTO_SHUTOFF_ON_ERRORS,
    'max_consecutive_losses': MAX_CONSECUTIVE_LOSSES,
    
    # Capital allocation
    'force_cash_buffer': FORCE_CASH_BUFFER,
    
    # Exchange settings
    'exchange_priority': EXCHANGE_PRIORITY,
    'min_balance_kraken': MIN_BALANCE_KRAKEN,
    'min_balance_coinbase': MIN_BALANCE_COINBASE,
    
    # Logging
    'log_signal_rejections': LOG_SIGNAL_REJECTIONS,
    'log_entry_block_reasons': LOG_ENTRY_BLOCK_REASONS,
    
    # State management
    'reset_strategy_state': RESET_STRATEGY_STATE,
    'clear_entry_blocks': CLEAR_ENTRY_BLOCKS,
    'flush_cached_balances': FLUSH_CACHED_BALANCES,
}

# ============================================================================
# ENVIRONMENT VARIABLE MAPPING
# ============================================================================

def get_environment_variables(equity: Optional[float] = None) -> Dict[str, str]:
    """
    Get environment variables for micro capital mode.
    
    Args:
        equity: Current account equity for dynamic scaling (optional)
        
    Returns:
        Dict of environment variable names and values
    """
    # Get dynamic config if equity provided
    dynamic_config = get_dynamic_config(equity) if equity else {}
    
    # Base environment variables
    env_vars = {
        'MICRO_CAPITAL_MODE': str(MICRO_CAPITAL_MODE).lower(),
        'MODE': MODE,
        'PRIMARY_BROKER': PRIMARY_BROKER,
        'SECONDARY_BROKER': SECONDARY_BROKER,
        
        'LIVE_TRADING': '1' if LIVE_TRADING else '0',
        'PRO_MODE': str(PRO_MODE).lower(),
        'COPY_TRADING_MODE': 'MASTER_FOLLOW' if dynamic_config.get('copy_trading', COPY_TRADING) else 'INDEPENDENT',
        
        'MINIMUM_TRADING_BALANCE': str(MIN_BALANCE_TO_TRADE),
        'MIN_CASH_TO_BUY': str(MIN_TRADE_SIZE),
        
        'MAX_CONCURRENT_POSITIONS': str(dynamic_config.get('max_positions', MAX_POSITIONS)),
        'MAX_POSITION_PCT': str(MAX_POSITION_PCT),
        'RISK_PER_TRADE': str(dynamic_config.get('risk_per_trade', RISK_PER_TRADE)),
        
        'DAILY_MAX_LOSS': str(DAILY_MAX_LOSS),
        'MAX_DRAWDOWN': str(MAX_DRAWDOWN),
        'POSITION_SIZER': POSITION_SIZER,
        
        'MIN_SIGNAL_SCORE': str(MIN_SIGNAL_SCORE),
        'MIN_AI_CONFIDENCE': str(MIN_AI_CONFIDENCE),
        'MIN_RISK_REWARD': str(MIN_RISK_REWARD),
        
        'TRADE_ONLY': ','.join(TRADE_ONLY),
        
        'MARKET_REGIME_ENGINE': str(MARKET_REGIME_ENGINE).lower(),
        'SIGNAL_ENSEMBLE': str(SIGNAL_ENSEMBLE).lower(),
        'AI_TRADE_FILTER': str(AI_TRADE_FILTER).lower(),
        
        'LEVERAGE_ENABLED': str(dynamic_config.get('leverage_enabled', LEVERAGE_ENABLED)).lower(),
        'ARBITRAGE': str(ARBITRAGE).lower(),
        
        'AUTO_SHUTOFF_ON_ERRORS': str(AUTO_SHUTOFF_ON_ERRORS).lower(),
        'MAX_CONSECUTIVE_LOSSES': str(MAX_CONSECUTIVE_LOSSES),
        
        'FORCE_CASH_BUFFER': str(FORCE_CASH_BUFFER),
        
        'EXCHANGE_PRIORITY': ','.join(EXCHANGE_PRIORITY),
        'MIN_BALANCE_KRAKEN': str(MIN_BALANCE_KRAKEN),
        'MIN_BALANCE_COINBASE': str(MIN_BALANCE_COINBASE),
        
        'LOG_SIGNAL_REJECTIONS': str(LOG_SIGNAL_REJECTIONS).lower(),
        'LOG_ENTRY_BLOCK_REASONS': str(LOG_ENTRY_BLOCK_REASONS).lower(),
        
        'RESET_STRATEGY_STATE': str(RESET_STRATEGY_STATE).lower(),
        'CLEAR_ENTRY_BLOCKS': str(CLEAR_ENTRY_BLOCKS).lower(),
        'FLUSH_CACHED_BALANCES': str(FLUSH_CACHED_BALANCES).lower(),
    }
    
    return env_vars


def apply_micro_capital_config(equity: Optional[float] = None, set_env_vars: bool = True) -> Dict:
    """
    Apply micro capital configuration.
    
    Args:
        equity: Current account equity for dynamic scaling (optional)
        set_env_vars: If True, sets environment variables. If False, only returns config.
        
    Returns:
        Dict with all configuration values and dynamic adjustments
    """
    # Get environment variables
    env_vars = get_environment_variables(equity)
    
    # Optionally set environment variables
    if set_env_vars:
        for key, value in env_vars.items():
            os.environ[key] = value
            logger.debug(f"Set {key} = {value}")
    
    # Get dynamic config if equity provided
    dynamic_config = get_dynamic_config(equity) if equity else {}
    
    # Return complete configuration
    return {
        'base_config': MICRO_CAPITAL_CONFIG,
        'dynamic_config': dynamic_config,
        'environment_variables': env_vars,
        'current_equity': equity,
    }


def get_config_summary(equity: Optional[float] = None) -> str:
    """
    Get human-readable summary of micro capital configuration.
    
    Args:
        equity: Current account equity for dynamic scaling display
        
    Returns:
        Formatted configuration summary
    """
    dynamic_config = get_dynamic_config(equity) if equity else {}
    
    max_positions = dynamic_config.get('max_positions', MAX_POSITIONS)
    risk_per_trade = dynamic_config.get('risk_per_trade', RISK_PER_TRADE)
    copy_trading = dynamic_config.get('copy_trading', COPY_TRADING)
    leverage_enabled = dynamic_config.get('leverage_enabled', LEVERAGE_ENABLED)
    
    equity_str = f"${equity:.2f}" if equity is not None else "$0.00"
    
    return f"""
╔══════════════════════════════════════════════════════════════════════════╗
║                  NIJA MICRO CAPITAL MODE CONFIGURATION                   ║
║                         Version 1.0                                       ║
╚══════════════════════════════════════════════════════════════════════════╝

📊 CURRENT EQUITY: {equity_str}

⚙️  OPERATIONAL MODE:
   • Mode: {MODE}
   • Micro Capital Mode: {MICRO_CAPITAL_MODE}
   • Primary Broker: {PRIMARY_BROKER}
   • Secondary Broker: {SECONDARY_BROKER}
   • Live Trading: {LIVE_TRADING}
   • PRO Mode: {PRO_MODE}

💰 BALANCE REQUIREMENTS:
   • Minimum Balance to Trade: ${MIN_BALANCE_TO_TRADE:.2f}
   • Minimum Trade Size: ${MIN_TRADE_SIZE:.2f}
   • Minimum Balance (Coinbase): ${MIN_BALANCE_COINBASE:.2f}
   • Minimum Balance (Kraken): ${MIN_BALANCE_KRAKEN:.2f}

📈 POSITION MANAGEMENT:
   • Max Concurrent Positions: {max_positions}
   • Max Position Size: {MAX_POSITION_PCT:.1f}% of capital
   • Risk Per Trade: {risk_per_trade:.1f}%
   • Position Sizer: {POSITION_SIZER}

🛡️  RISK MANAGEMENT:
   • Daily Max Loss: {DAILY_MAX_LOSS:.1f}%
   • Max Drawdown: {MAX_DRAWDOWN:.1f}%
   • Kelly Weight: {KELLY_WEIGHT:.0%}
   • Volatility Weight: {VOLATILITY_WEIGHT:.0%}
   • Equity Weight: {EQUITY_WEIGHT:.0%}

🎯 SIGNAL FILTERING:
   • Min Signal Score: {MIN_SIGNAL_SCORE:.0%}
   • Min AI Confidence: {MIN_AI_CONFIDENCE:.0%}
   • Min Risk/Reward: {MIN_RISK_REWARD:.1f}

💱 TRADING PAIRS:
   • Allowed: {', '.join(TRADE_ONLY)}
   • Exchange Priority: {' > '.join(EXCHANGE_PRIORITY)}

🔥 ADVANCED FEATURES:
   • Market Regime Engine: {MARKET_REGIME_ENGINE}
   • Signal Ensemble: {SIGNAL_ENSEMBLE}
   • AI Trade Filter: {AI_TRADE_FILTER}
   • Copy Trading: {copy_trading} {'(auto-enabled at $500+)' if not copy_trading and equity and equity < 500 else ''}
   • Leverage: {leverage_enabled} {'(auto-enabled at $1000+)' if not leverage_enabled and equity and equity < 1000 else ''}
   • Arbitrage: {ARBITRAGE}

🚨 SAFETY FEATURES:
   • Auto-Shutoff on Errors: {AUTO_SHUTOFF_ON_ERRORS}
   • Max Consecutive Losses: {MAX_CONSECUTIVE_LOSSES}
   • Cash Buffer: {FORCE_CASH_BUFFER:.1f}%

📊 DYNAMIC SCALING THRESHOLDS:
   • $250+: 3 positions, 4% risk per trade
   • $500+: 4 positions, copy trading enabled
   • $1000+: 6 positions, 5% risk, leverage enabled

📝 LOGGING:
   • Log Signal Rejections: {LOG_SIGNAL_REJECTIONS}
   • Log Entry Block Reasons: {LOG_ENTRY_BLOCK_REASONS}

🔄 STATE MANAGEMENT:
   • Reset Strategy State: {RESET_STRATEGY_STATE}
   • Clear Entry Blocks: {CLEAR_ENTRY_BLOCKS}
   • Flush Cached Balances: {FLUSH_CACHED_BALANCES}

═══════════════════════════════════════════════════════════════════════════

This configuration is optimized for:
✅ Micro capital accounts ($15-$500)
✅ Conservative risk management
✅ Dynamic scaling as equity grows
✅ Multi-broker support
✅ Advanced AI and signal filtering
✅ Automatic feature enablement

To activate: apply_micro_capital_config(equity=your_balance)
"""


if __name__ == "__main__":
    # Print configuration summary at different equity levels
    print("="*80)
    print("MICRO CAPITAL MODE CONFIGURATION - DEMO")
    print("="*80)
    
    print("\n" + "="*80)
    print("STARTING ACCOUNT ($15)")
    print("="*80)
    print(get_config_summary(equity=15.0))
    
    print("\n" + "="*80)
    print("SCALED ACCOUNT ($250)")
    print("="*80)
    print(get_config_summary(equity=250.0))
    
    print("\n" + "="*80)
    print("COPY TRADING ENABLED ($500)")
    print("="*80)
    print(get_config_summary(equity=500.0))
    
    print("\n" + "="*80)
    print("FULL FEATURES ($1000)")
    print("="*80)
    print(get_config_summary(equity=1000.0))
    
    print("\n" + "="*80)
    print("APPLYING CONFIGURATION")
    print("="*80)
    config = apply_micro_capital_config(equity=100.0, set_env_vars=False)
    print(f"✅ Configuration applied successfully!")
    print(f"   Base Config Keys: {len(config['base_config'])}")
    print(f"   Dynamic Config: {config['dynamic_config']}")
    print(f"   Environment Variables: {len(config['environment_variables'])}")
