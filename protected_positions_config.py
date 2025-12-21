#!/usr/bin/env python3
"""
PROTECTED POSITIONS CONFIG
Tells Nija to NOT trade these existing positions, only manage them for minimal loss
"""

PROTECTED_POSITIONS = {
    'BTC-USD': {
        'amount': 0.000505,
        'entry_price': 87900.0,
        'current_loss': -0.52,
        'action': 'MONITOR_ONLY',
        'reason': 'Existing position - DO NOT TRADE'
    },
    'XRP-USD': {
        'amount': 12.981495,
        'entry_price': 1.9050,
        'current_loss': -0.27,
        'action': 'MONITOR_ONLY',
        'reason': 'Existing position - DO NOT TRADE'
    },
    'ETH-USD': {
        'amount': 0.005292,
        'entry_price': 3250.0,
        'current_loss': -0.25,
        'action': 'MONITOR_ONLY',
        'reason': 'Existing position - DO NOT TRADE'
    },
    'SOL-USD': {
        'amount': 0.11903,
        'entry_price': 124.50,
        'current_loss': -0.17,
        'action': 'MONITOR_ONLY',
        'reason': 'Existing position - DO NOT TRADE'
    },
    'DOGE-USD': {
        'amount': 114.6,
        'entry_price': 0.1295,
        'current_loss': -0.18,
        'action': 'MONITOR_ONLY',
        'reason': 'Existing position - DO NOT TRADE'
    },
    'ATOM-USD': {
        'amount': 0.305094,
        'entry_price': 1.93,
        'current_loss': 0.00,
        'action': 'MONITOR_ONLY - STAKING',
        'reason': 'Existing position - DO NOT TRADE'
    }
}

# LIQUIDATION STRATEGY
# Only liquidate if:
# 1. Any position breaks even (0% loss) - SELL IMMEDIATELY
# 2. Any position reaches +2% profit - SELL IMMEDIATELY
# 3. Any position exceeds -5% loss and market reversal unlikely - CONSIDER LIQUIDATION

LIQUIDATION_RULES = {
    'breakeven_threshold': 0.0,  # 0% - sell any position that hits breakeven
    'profit_target': 0.02,        # 2% - sell on any 2% gain
    'max_loss_tolerance': -0.05,  # -5% - consider selling at max 5% loss
    'stop_loss': -0.10            # -10% - hard stop loss
}

# NIJA ACTIVE TRADING RULES
# Nija can ONLY trade NEW positions with these rules:
ACTIVE_TRADING_CONFIG = {
    'enabled': True,
    'only_new_positions': True,
    'protected_positions': list(PROTECTED_POSITIONS.keys()),
    'do_not_trade': ['BTC-USD', 'XRP-USD', 'ETH-USD', 'SOL-USD', 'DOGE-USD', 'ATOM-USD'],
    'max_new_positions': 3,
    'position_size': 'MICRO',  # Very small positions until account recovers
    'take_profit_pct': 0.02,    # 2% quick profit
    'stop_loss_pct': 0.015,     # 1.5% stop loss
    'message': 'CRITICAL: Account has 6 existing losing positions. Nija will MONITOR only, NOT trade these. Can open new positions in OTHER pairs with micro sizing.'
}
