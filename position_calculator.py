#!/usr/bin/env python3
"""
8-POSITION EQUAL CAPITAL TRADING CONFIG
Ensures NIJA always trades 8 positions with equal allocation
"""

# Maximum concurrent positions: 8
MAX_CONCURRENT_POSITIONS = 8

# Calculate position size based on balance
def calculate_position_size(available_balance):
    """
    Split available balance equally across 8 positions
    Example: $120 balance = $15 per position
    """
    # Keep $15 minimum reserved
    tradable = max(0, available_balance - 15)
    
    # Divide equally across 8 positions
    per_position = tradable / MAX_CONCURRENT_POSITIONS
    
    # Minimum per trade: $5
    # Maximum per trade: $30 (scales with balance)
    per_position = max(5, min(per_position, 30))
    
    return {
        'total_tradable': tradable,
        'per_position': per_position,
        'max_positions': MAX_CONCURRENT_POSITIONS,
        'reserved_minimum': 15
    }

# STRICT STOP LOSS - prevents bleeding
STOP_LOSS_PERCENT = 0.015  # 1.5% - tight stop to prevent losses

# IMMEDIATE EXIT SIGNALS
EXIT_CONDITIONS = {
    'stop_loss': True,  # MUST exit on stop loss
    'opposite_signal': True,  # Exit if trend reverses
    'time_limit': 3600,  # Exit after 1 hour if no profit
    'max_loss': 0.015  # 1.5% max loss
}

# PROFIT LOCKING - secure gains immediately
PROFIT_TARGETS = {
    'take_profit_1': 0.02,  # 2% = immediate profit lock
    'trailing_stop': True,  # Lock 98% of gains, trail at 2%
    'trailing_lock_pct': 0.98  # Keep 98% of max profit
}

# EXAMPLES
if __name__ == "__main__":
    print("="*80)
    print("8-POSITION EQUAL CAPITAL CALCULATOR")
    print("="*80)
    print()
    
    test_balances = [50, 100, 200, 500, 1000]
    
    for balance in test_balances:
        config = calculate_position_size(balance)
        print(f"Balance: ${balance:.2f}")
        print(f"  Reserve (protected): ${config['reserved_minimum']:.2f}")
        print(f"  Tradable capital: ${config['total_tradable']:.2f}")
        print(f"  Per position: ${config['per_position']:.2f}")
        print(f"  Max concurrent: {config['max_positions']}")
        print()
        
        # Show what happens with stop loss
        loss_per_position = config['per_position'] * STOP_LOSS_PERCENT
        print(f"  If position hits stop loss:")
        print(f"    Loss per position: ${loss_per_position:.2f}")
        print(f"    Max total loss: ${loss_per_position * config['max_positions']:.2f}")
        print()
        
        # Show profit scenario
        profit_per_position = config['per_position'] * PROFIT_TARGETS['take_profit_1']
        print(f"  If position hits 2% profit:")
        print(f"    Profit per position: ${profit_per_position:.2f}")
        print(f"    Max profit (8 wins): ${profit_per_position * config['max_positions']:.2f}")
        print()

