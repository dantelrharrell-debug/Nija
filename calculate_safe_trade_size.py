#!/usr/bin/env python3
"""
NIJA Safe Trade Size Calculator
================================
Calculate exact maximum safe trade size for any tier/balance combination.

This script accounts for:
- Tier-based trade size limits (min/max)
- Fee-aware configuration (Coinbase fees ~1.4% round-trip)
- Position sizer minimums ($2.00 minimum position)
- Risk management rules
- Tier override scenarios

Usage:
    python calculate_safe_trade_size.py --balance 62.49 --tier BALLER
    python calculate_safe_trade_size.py --balance 62.49  # Auto-detect tier
"""

import sys
import argparse
from typing import Dict, Tuple

# Import NIJA modules
sys.path.insert(0, './bot')

from tier_config import (
    TradingTier, 
    TIER_CONFIGS, 
    get_tier_from_balance,
    get_tier_config,
    validate_trade_size,
    get_min_trade_size,
    get_max_trade_size
)
from position_sizer import MIN_POSITION_USD, calculate_user_position_size
from fee_aware_config import (
    COINBASE_MARKET_ORDER_FEE,
    COINBASE_LIMIT_ORDER_FEE,
    COINBASE_SPREAD_COST,
    MARKET_ORDER_ROUND_TRIP,
    LIMIT_ORDER_ROUND_TRIP,
    get_position_size_pct,
    calculate_min_position_size,
    MIN_BALANCE_TO_TRADE,
    MICRO_ACCOUNT_THRESHOLD,
    get_min_profit_target
)


def calculate_fees(trade_size: float, use_limit_order: bool = True) -> Dict[str, float]:
    """
    Calculate all fees for a trade.
    
    Args:
        trade_size: Trade size in USD
        use_limit_order: True for limit orders (0.4% maker), False for market (0.6% taker)
    
    Returns:
        Dictionary with fee breakdown
    """
    if use_limit_order:
        entry_fee_pct = COINBASE_LIMIT_ORDER_FEE
        exit_fee_pct = COINBASE_LIMIT_ORDER_FEE
        round_trip_pct = LIMIT_ORDER_ROUND_TRIP
    else:
        entry_fee_pct = COINBASE_MARKET_ORDER_FEE
        exit_fee_pct = COINBASE_MARKET_ORDER_FEE
        round_trip_pct = MARKET_ORDER_ROUND_TRIP
    
    entry_fee = trade_size * entry_fee_pct
    spread_cost = trade_size * COINBASE_SPREAD_COST
    exit_fee = trade_size * exit_fee_pct
    total_fees = entry_fee + spread_cost + exit_fee
    
    return {
        'entry_fee': entry_fee,
        'entry_fee_pct': entry_fee_pct * 100,
        'spread_cost': spread_cost,
        'spread_cost_pct': COINBASE_SPREAD_COST * 100,
        'exit_fee': exit_fee,
        'exit_fee_pct': exit_fee_pct * 100,
        'total_fees': total_fees,
        'total_fees_pct': round_trip_pct * 100,
        'order_type': 'limit' if use_limit_order else 'market'
    }


def calculate_safe_trade_size(balance: float, tier: TradingTier = None, 
                              use_limit_order: bool = True, is_master: bool = False) -> Dict:
    """
    Calculate the exact safe trade size for a given balance and tier.
    
    MASTER ACCOUNT MODE:
    When is_master=True with BALLER tier, applies flexible limits for low balances.
    This allows master to maintain control even with small funded accounts.
    
    Args:
        balance: Account balance in USD
        tier: TradingTier enum (if None, auto-detect from balance)
        use_limit_order: True for limit orders (lower fees)
        is_master: True if this is the master account (gets BALLER flexibility)
    
    Returns:
        Dictionary with complete calculation breakdown
    """
    # Determine actual tier from balance
    actual_tier = get_tier_from_balance(balance, is_master=is_master)
    
    # Use specified tier or actual tier
    if tier is None:
        tier = actual_tier
    
    tier_config = get_tier_config(tier)
    
    # Check if balance meets minimum to trade
    if balance < MIN_BALANCE_TO_TRADE:
        return {
            'can_trade': False,
            'reason': f'Balance ${balance:.2f} below minimum ${MIN_BALANCE_TO_TRADE:.2f}',
            'balance': balance,
            'tier': tier.value,
            'actual_tier': actual_tier.value,
            'tier_match': tier == actual_tier
        }
    
    # Fee-aware position size percentage
    fee_aware_pct = get_position_size_pct(balance)
    fee_aware_size = balance * fee_aware_pct
    
    # Tier-based size limits (with master account flexibility)
    tier_min = get_min_trade_size(tier, balance, is_master)
    tier_max = get_max_trade_size(tier, balance, is_master)
    
    # Position sizer minimum
    position_sizer_min = MIN_POSITION_USD
    
    # Calculate suggested trade size
    # Start with fee-aware calculation
    suggested_size = fee_aware_size
    
    # Apply tier risk limits FIRST (important!)
    # BALLER: max 2% of balance, LIVABLE: max 3%, etc.
    max_risk_size = balance * tier_config.risk_per_trade_pct[1] / 100
    if suggested_size > max_risk_size:
        suggested_size = max_risk_size
    
    # Apply tier limits
    if suggested_size < tier_min:
        suggested_size = tier_min
    if suggested_size > tier_max:
        suggested_size = tier_max
    
    # Apply position sizer minimum
    if suggested_size < position_sizer_min:
        suggested_size = position_sizer_min
    
    # Final check: Cannot exceed available balance (CRITICAL!)
    if suggested_size > balance:
        suggested_size = balance
    
    # Validate against tier (with master account support)
    is_valid, validation_reason = validate_trade_size(suggested_size, tier, balance, is_master)
    
    # Calculate fees for this trade size
    fees = calculate_fees(suggested_size, use_limit_order)
    
    # Calculate minimum profit needed to break even
    min_profit_target_pct = get_min_profit_target(use_limit_order, balance)
    min_profit_dollars = suggested_size * min_profit_target_pct
    breakeven_price_pct = fees['total_fees_pct']
    
    # Calculate how much can actually be deployed after fees
    effective_trade_size = suggested_size - fees['entry_fee']
    
    result = {
        'can_trade': is_valid,
        'validation_reason': validation_reason,
        'balance': balance,
        'tier': tier.value,
        'actual_tier': actual_tier.value,
        'tier_match': tier == actual_tier,
        'is_master': is_master,
        
        # Trade size calculations
        'fee_aware_pct': fee_aware_pct * 100,
        'fee_aware_size': fee_aware_size,
        'tier_min': tier_min,
        'tier_max': tier_max,
        'position_sizer_min': position_sizer_min,
        'suggested_trade_size': suggested_size,
        'effective_trade_size': effective_trade_size,
        
        # Tier configuration
        'tier_config': {
            'capital_range': f"${tier_config.capital_min:.2f} - ${tier_config.capital_max:.2f}",
            'risk_per_trade': f"{tier_config.risk_per_trade_pct[0]:.1f}% - {tier_config.risk_per_trade_pct[1]:.1f}%",
            'trade_size_range': f"${tier_config.trade_size_min:.2f} - ${tier_config.trade_size_max:.2f}",
            'max_positions': tier_config.max_positions,
            'description': tier_config.description
        },
        
        # Fee breakdown
        'fees': fees,
        
        # Profitability
        'breakeven_price_movement_pct': breakeven_price_pct,
        'min_profit_target_pct': min_profit_target_pct * 100,
        'min_profit_dollars': min_profit_dollars,
        
        # Warnings
        'warnings': []
    }
    
    # Generate warnings
    if tier != actual_tier:
        result['warnings'].append(
            f"⚠️  TIER MISMATCH: Balance ${balance:.2f} should use {actual_tier.value} tier, "
            f"but {tier.value} tier is specified. This requires manual override."
        )
    
    if balance < tier_config.capital_min:
        result['warnings'].append(
            f"⚠️  UNDERCAPITALIZED: Balance ${balance:.2f} is below {tier.value} tier minimum "
            f"${tier_config.capital_min:.2f}"
        )
    
    if suggested_size < tier_min and balance >= tier_min:
        result['warnings'].append(
            f"⚠️  POSITION TOO SMALL: Calculated size ${suggested_size:.2f} is below tier minimum "
            f"${tier_min:.2f}"
        )
    
    if suggested_size < 10.0:
        result['warnings'].append(
            f"⚠️  MICRO POSITION: Trade size ${suggested_size:.2f} faces severe fee pressure "
            f"({fees['total_fees_pct']:.2f}% round-trip). Profitability is very challenging."
        )
    
    if balance < MICRO_ACCOUNT_THRESHOLD:
        result['warnings'].append(
            f"⚠️  MICRO ACCOUNT: Balance ${balance:.2f} is below ${MICRO_ACCOUNT_THRESHOLD:.2f}. "
            f"Quality multipliers are bypassed to enable trading, but profitability is limited."
        )
    
    # Add recommendation
    if not is_valid:
        result['recommendation'] = "Cannot trade - validation failed"
    elif tier != actual_tier:
        result['recommendation'] = f"Switch to {actual_tier.value} tier for proper risk management"
    elif suggested_size < 10.0:
        result['recommendation'] = "Fund account to $30+ for viable trading"
    else:
        result['recommendation'] = "Trade size is appropriate for balance and tier"
    
    return result


def print_calculation_report(result: Dict) -> None:
    """
    Pretty-print the calculation results.
    
    Args:
        result: Dictionary from calculate_safe_trade_size()
    """
    print("\n" + "="*80)
    print("NIJA SAFE TRADE SIZE CALCULATION")
    print("="*80)
    
    print(f"\n💰 ACCOUNT INFORMATION:")
    print(f"   Balance: ${result['balance']:.2f}")
    print(f"   Current Tier: {result['tier']}")
    if result.get('is_master'):
        print(f"   Account Type: 🎯 MASTER (Full Control)")
    print(f"   Appropriate Tier: {result['actual_tier']}")
    print(f"   Tier Match: {'✅ YES' if result['tier_match'] else '⚠️  NO (Manual Override)'}")
    
    print(f"\n📊 TIER CONFIGURATION ({result['tier']}):")
    tc = result['tier_config']
    print(f"   Capital Range: {tc['capital_range']}")
    print(f"   Risk Per Trade: {tc['risk_per_trade']}")
    print(f"   Trade Size Range: {tc['trade_size_range']}")
    print(f"   Max Positions: {tc['max_positions']}")
    print(f"   Description: {tc['description']}")
    
    print(f"\n🎯 TRADE SIZE CALCULATION:")
    print(f"   Fee-Aware %: {result['fee_aware_pct']:.1f}%")
    print(f"   Fee-Aware Size: ${result['fee_aware_size']:.2f}")
    print(f"   Tier Minimum: ${result['tier_min']:.2f}")
    print(f"   Tier Maximum: ${result['tier_max']:.2f}")
    print(f"   Position Sizer Minimum: ${result['position_sizer_min']:.2f}")
    print(f"   ───────────────────────────────")
    print(f"   SUGGESTED TRADE SIZE: ${result['suggested_trade_size']:.2f}")
    print(f"   Effective (after entry fee): ${result['effective_trade_size']:.2f}")
    
    print(f"\n💸 FEE BREAKDOWN ({result['fees']['order_type']} orders):")
    print(f"   Entry Fee: ${result['fees']['entry_fee']:.4f} ({result['fees']['entry_fee_pct']:.2f}%)")
    print(f"   Spread Cost: ${result['fees']['spread_cost']:.4f} ({result['fees']['spread_cost_pct']:.2f}%)")
    print(f"   Exit Fee: ${result['fees']['exit_fee']:.4f} ({result['fees']['exit_fee_pct']:.2f}%)")
    print(f"   ───────────────────────────────")
    print(f"   TOTAL FEES: ${result['fees']['total_fees']:.4f} ({result['fees']['total_fees_pct']:.2f}%)")
    
    print(f"\n📈 PROFITABILITY REQUIREMENTS:")
    print(f"   Breakeven Price Movement: {result['breakeven_price_movement_pct']:.2f}%")
    print(f"   Minimum Profit Target: {result['min_profit_target_pct']:.2f}%")
    print(f"   Minimum Profit (USD): ${result['min_profit_dollars']:.4f}")
    
    print(f"\n✅ VALIDATION:")
    print(f"   Can Trade: {'✅ YES' if result['can_trade'] else '❌ NO'}")
    print(f"   Reason: {result['validation_reason']}")
    
    if result['warnings']:
        print(f"\n⚠️  WARNINGS:")
        for warning in result['warnings']:
            print(f"   {warning}")
    
    print(f"\n💡 RECOMMENDATION:")
    print(f"   {result['recommendation']}")
    
    print("\n" + "="*80)
    print(f"MAXIMUM SAFE TRADE SIZE: ${result['suggested_trade_size']:.2f}")
    print("="*80 + "\n")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Calculate safe trade size for NIJA bot with fee/safety rules',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Calculate for $62.49 with BALLER tier (manual override)
  python calculate_safe_trade_size.py --balance 62.49 --tier BALLER
  
  # Calculate for $62.49 with auto-detected tier
  python calculate_safe_trade_size.py --balance 62.49
  
  # Calculate for $25,000 with BALLER tier (proper usage)
  python calculate_safe_trade_size.py --balance 25000 --tier BALLER
  
  # Calculate with market orders instead of limit orders
  python calculate_safe_trade_size.py --balance 62.49 --tier BALLER --market-order
        """
    )
    
    parser.add_argument('--balance', type=float, required=True,
                       help='Account balance in USD')
    parser.add_argument('--tier', type=str, choices=['STARTER', 'SAVER', 'INVESTOR', 'INCOME', 'LIVABLE', 'BALLER'],
                       help='Trading tier (default: auto-detect from balance)')
    parser.add_argument('--master', action='store_true',
                       help='Enable master account mode (BALLER tier with flexible limits at low balances)')
    parser.add_argument('--market-order', action='store_true',
                       help='Use market order fees (0.6%%) instead of limit order fees (0.4%%)')
    
    args = parser.parse_args()
    
    # Convert tier string to enum if provided
    tier = None
    if args.tier:
        tier = TradingTier[args.tier.upper()]
    
    # Calculate safe trade size
    result = calculate_safe_trade_size(
        balance=args.balance,
        tier=tier,
        use_limit_order=not args.market_order,
        is_master=args.master
    )
    
    # Print report
    print_calculation_report(result)
    
    # Return exit code based on can_trade
    return 0 if result['can_trade'] else 1


if __name__ == '__main__':
    sys.exit(main())
