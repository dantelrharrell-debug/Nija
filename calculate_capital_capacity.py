#!/usr/bin/env python3
"""
NIJA Capital Capacity Calculator
=================================

Calculate and display effective deployable capital and max position size
for all accounts (master and user accounts).

This script provides a comprehensive view of:
- Total equity (cash + positions)
- Deployable capital (what can still be used for new positions)
- Maximum position size per trade
- Capital utilization and capacity metrics

Usage:
    # Calculate for a single account with balance and positions
    python calculate_capital_capacity.py --balance 10000 --positions 2000

    # Calculate for account with no open positions
    python calculate_capital_capacity.py --balance 5000

    # Custom reserve and max position percentage
    python calculate_capital_capacity.py --balance 10000 --positions 2000 --reserve-pct 15 --max-position-pct 20
"""

import sys
import argparse
from typing import Dict

# Import NIJA modules
sys.path.insert(0, './bot')

from portfolio_state import PortfolioState


def print_capital_breakdown(breakdown: Dict, account_name: str = "Account") -> None:
    """
    Pretty-print the capital breakdown.
    
    Args:
        breakdown: Dictionary from get_capital_breakdown()
        account_name: Name of the account for display
    """
    print("\n" + "="*80)
    print(f"CAPITAL CAPACITY ANALYSIS - {account_name}")
    print("="*80)
    
    print(f"\n💰 ACCOUNT BALANCES:")
    print(f"   Total Equity: ${breakdown['total_equity']:,.2f}")
    print(f"   Available Cash: ${breakdown['available_cash']:,.2f}")
    print(f"   Position Value: ${breakdown['total_position_value']:,.2f}")
    print(f"   Unrealized P/L: ${breakdown['unrealized_pnl']:+,.2f}")
    
    print(f"\n📊 POSITION METRICS:")
    print(f"   Open Positions: {breakdown['position_count']}")
    print(f"   Cash Utilization: {breakdown['cash_utilization_pct']:.1f}%")
    
    print(f"\n🎯 CAPITAL DEPLOYMENT:")
    print(f"   Min Reserve Required: {breakdown['min_reserve_pct']:.1f}% (${breakdown['min_reserve_amount']:,.2f})")
    print(f"   Max Deployable Total: ${breakdown['max_deployable_total']:,.2f}")
    print(f"   Currently Deployed: ${breakdown['current_deployed']:,.2f}")
    print(f"   ──────────────────────────────────────")
    print(f"   EFFECTIVE DEPLOYABLE CAPITAL: ${breakdown['deployable_capital']:,.2f}")
    
    print(f"\n📏 POSITION SIZING:")
    print(f"   Max Position %: {breakdown['max_position_pct']:.1f}%")
    print(f"   ──────────────────────────────────────")
    print(f"   MAX POSITION SIZE: ${breakdown['max_position_size']:,.2f}")
    
    print(f"\n📈 CAPACITY METRICS:")
    print(f"   Deployment Capacity Used: {breakdown['deployment_capacity_used_pct']:.1f}%")
    print(f"   Remaining Capacity: ${breakdown['remaining_capacity']:,.2f}")
    
    # Provide recommendations
    print(f"\n💡 RECOMMENDATIONS:")
    
    if breakdown['deployable_capital'] <= 0:
        print(f"   ⚠️  WARNING: No deployable capital available!")
        print(f"   → Consider closing positions or adding capital to enable new trades")
    elif breakdown['deployable_capital'] < breakdown['max_position_size']:
        print(f"   ⚠️  LIMITED CAPACITY: Deployable capital (${breakdown['deployable_capital']:,.2f}) is less than")
        print(f"      max position size (${breakdown['max_position_size']:,.2f})")
        print(f"   → Can only open positions up to ${breakdown['deployable_capital']:,.2f}")
    else:
        print(f"   ✅ HEALTHY CAPACITY: Can open new positions up to ${breakdown['max_position_size']:,.2f}")
    
    if breakdown['cash_utilization_pct'] > 80:
        print(f"   ⚠️  HIGH UTILIZATION: {breakdown['cash_utilization_pct']:.1f}% of equity is in positions")
        print(f"   → Consider risk management - portfolio is heavily deployed")
    elif breakdown['cash_utilization_pct'] < 20:
        print(f"   💼 LOW UTILIZATION: {breakdown['cash_utilization_pct']:.1f}% of equity is in positions")
        print(f"   → Significant capital available for deployment")
    
    print("\n" + "="*80)
    print(f"SUMMARY: ${breakdown['deployable_capital']:,.2f} deployable | "
          f"${breakdown['max_position_size']:,.2f} max position | "
          f"{breakdown['position_count']} open positions")
    print("="*80 + "\n")


def calculate_portfolio_capacity(
    balance: float,
    position_value: float = 0.0,
    unrealized_pnl: float = 0.0,
    min_reserve_pct: float = 10.0,
    max_position_pct: float = 15.0
) -> Dict:
    """
    Calculate capital capacity for a portfolio.
    
    Args:
        balance: Available cash balance
        position_value: Total value of open positions (default: 0)
        unrealized_pnl: Unrealized P/L from positions (default: 0)
        min_reserve_pct: Minimum reserve percentage to maintain (default: 10%)
        max_position_pct: Maximum position size as % of equity (default: 15%)
        
    Returns:
        Dictionary with capital breakdown
    """
    # Create portfolio state
    # Total equity = cash + positions
    # Available cash is what we have free
    portfolio = PortfolioState(
        available_cash=balance,
        min_reserve_pct=min_reserve_pct / 100.0
    )
    
    # Add a dummy position if there's position value
    # This is just for calculation purposes to simulate deployed capital
    if position_value > 0:
        # Create a synthetic position to represent deployed capital
        # Note: We use position_value for both entry and current price
        # because we don't have actual position details
        portfolio.add_position(
            symbol="DEPLOYED_CAPITAL",  # Clearer name than AGGREGATE_POSITIONS
            quantity=1.0,
            entry_price=position_value,
            current_price=position_value
        )
    
    # Get capital breakdown
    breakdown = portfolio.get_capital_breakdown(
        max_position_pct=max_position_pct / 100.0,
        min_reserve_pct=min_reserve_pct / 100.0
    )
    
    return breakdown


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Calculate effective deployable capital and max position size',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Account with $10,000 balance and $2,000 in open positions
  python calculate_capital_capacity.py --balance 10000 --positions 2000
  
  # Account with $5,000 balance, no positions
  python calculate_capital_capacity.py --balance 5000
  
  # Account with custom reserve (15%) and max position (20%)
  python calculate_capital_capacity.py --balance 10000 --positions 2000 --reserve-pct 15 --max-position-pct 20
  
  # Small account with positions
  python calculate_capital_capacity.py --balance 100 --positions 50
        """
    )
    
    parser.add_argument('--balance', type=float, required=True,
                       help='Account balance (total equity = balance + positions)')
    parser.add_argument('--positions', type=float, default=0.0,
                       help='Total value of open positions in USD (default: 0)')
    parser.add_argument('--unrealized-pnl', type=float, default=0.0,
                       help='Unrealized profit/loss from positions (default: 0)')
    parser.add_argument('--reserve-pct', type=float, default=10.0,
                       help='Minimum reserve percentage to maintain (default: 10%%)')
    parser.add_argument('--max-position-pct', type=float, default=15.0,
                       help='Maximum position size as %% of total equity (default: 15%%)')
    parser.add_argument('--account-name', type=str, default="Account",
                       help='Account name for display (default: "Account")')
    
    args = parser.parse_args()
    
    # Validate inputs
    if args.balance < 0:
        print("❌ Error: Balance cannot be negative")
        return 1
    
    if args.positions < 0:
        print("❌ Error: Position value cannot be negative")
        return 1
    
    if args.reserve_pct < 0 or args.reserve_pct > 100:
        print("❌ Error: Reserve percentage must be between 0 and 100")
        return 1
    
    if args.max_position_pct <= 0 or args.max_position_pct > 100:
        print("❌ Error: Max position percentage must be between 0 and 100")
        return 1
    
    # Calculate capital capacity
    breakdown = calculate_portfolio_capacity(
        balance=args.balance,
        position_value=args.positions,
        unrealized_pnl=args.unrealized_pnl,
        min_reserve_pct=args.reserve_pct,
        max_position_pct=args.max_position_pct
    )
    
    # Print breakdown
    print_capital_breakdown(breakdown, args.account_name)
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
