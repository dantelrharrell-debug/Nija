#!/usr/bin/env python3
"""
NIJA All Accounts Capital Calculator
====================================

Calculate and display effective deployable capital and max position size
for ALL accounts (master account + all user accounts).

This provides a comprehensive portfolio-wide view of capital capacity.

Usage:
    # Display all accounts from portfolio manager
    python calculate_all_accounts_capital.py

    # Simulate with example accounts
    python calculate_all_accounts_capital.py --simulate
"""

import sys
import argparse
from typing import Dict, List

# Import NIJA modules
sys.path.insert(0, './bot')

from portfolio_state import PortfolioState, UserPortfolioState, get_portfolio_manager


def print_account_summary(
    account_name: str,
    breakdown: Dict,
    account_type: str = "User"
) -> None:
    """
    Print a compact summary for one account.

    Args:
        account_name: Name/ID of the account
        breakdown: Capital breakdown dictionary
        account_type: "Master" or "User"
    """
    icon = "🎯" if account_type == "Master" else "👤"

    print(f"\n{icon} {account_name} ({account_type})")
    print(f"{'─' * 78}")
    print(f"  Total Equity:        ${breakdown['total_equity']:>12,.2f}")
    print(f"  Available Cash:      ${breakdown['available_cash']:>12,.2f}")
    print(f"  Position Value:      ${breakdown['total_position_value']:>12,.2f}")
    print(f"  Open Positions:      {breakdown['position_count']:>12}")
    print(f"  Utilization:         {breakdown['cash_utilization_pct']:>11.1f}%")
    print(f"  ────────────────────────────────────────────────")
    print(f"  💰 Deployable Capital: ${breakdown['deployable_capital']:>10,.2f}")
    print(f"  📏 Max Position Size:  ${breakdown['max_position_size']:>10,.2f}")


def print_aggregate_summary(all_breakdowns: List[Dict], account_names: List[str]) -> None:
    """
    Print an aggregate summary across all accounts.

    Args:
        all_breakdowns: List of capital breakdowns
        account_names: List of account names
    """
    total_equity = sum(b['total_equity'] for b in all_breakdowns)
    total_cash = sum(b['available_cash'] for b in all_breakdowns)
    total_positions = sum(b['total_position_value'] for b in all_breakdowns)
    total_deployable = sum(b['deployable_capital'] for b in all_breakdowns)
    total_max_position = sum(b['max_position_size'] for b in all_breakdowns)
    total_position_count = sum(b['position_count'] for b in all_breakdowns)

    avg_utilization = sum(b['cash_utilization_pct'] for b in all_breakdowns) / len(all_breakdowns) if all_breakdowns else 0

    print(f"\n{'=' * 80}")
    print(f"AGGREGATE SUMMARY - ALL {len(account_names)} ACCOUNTS")
    print(f"{'=' * 80}")
    print(f"\n💼 PORTFOLIO TOTALS:")
    print(f"   Total Equity (All Accounts):     ${total_equity:>15,.2f}")
    print(f"   Total Available Cash:             ${total_cash:>15,.2f}")
    print(f"   Total Position Value:             ${total_positions:>15,.2f}")
    print(f"   Total Open Positions:             {total_position_count:>15}")
    print(f"   Average Utilization:              {avg_utilization:>14.1f}%")

    print(f"\n🎯 AGGREGATE CAPACITY:")
    print(f"   Combined Deployable Capital:      ${total_deployable:>15,.2f}")
    print(f"   Combined Max Position Size:       ${total_max_position:>15,.2f}")

    print(f"\n📊 CAPACITY DISTRIBUTION:")
    for i, (name, breakdown) in enumerate(zip(account_names, all_breakdowns)):
        pct_of_total_equity = (breakdown['total_equity'] / total_equity * 100) if total_equity > 0 else 0
        pct_of_deployable = (breakdown['deployable_capital'] / total_deployable * 100) if total_deployable > 0 else 0
        print(f"   {name:30} {pct_of_total_equity:5.1f}% equity  |  {pct_of_deployable:5.1f}% deployable")

    print(f"\n{'=' * 80}")


def simulate_example_accounts() -> List[tuple]:
    """
    Create simulated example accounts for demonstration.

    Note: Cryptocurrency prices used here are for example purposes only
    and do not reflect actual market prices.

    Returns:
        List of (account_name, account_type, portfolio_state) tuples
    """
    accounts = []

    # Platform account - well funded
    master = PortfolioState(available_cash=20000.0, min_reserve_pct=0.10)
    # Example: BTC position with profit (prices are illustrative)
    master.add_position("BTC-USD", 0.1, 45000, 46000)  # $4,600 position
    accounts.append(("Platform Account", "Master", master))

    # User 1 - moderate account
    user1 = UserPortfolioState(
        available_cash=5000.0,
        user_id="user_001",
        broker_type="coinbase",
        min_reserve_pct=0.10
    )
    user1.add_position("ETH-USD", 1.5, 3000, 3100)  # $4,650 position
    accounts.append(("user_001 (Coinbase)", "User", user1))

    # User 2 - small account
    user2 = UserPortfolioState(
        available_cash=500.0,
        user_id="user_002",
        broker_type="kraken",
        min_reserve_pct=0.10
    )
    accounts.append(("user_002 (Kraken)", "User", user2))

    # User 3 - fully deployed
    user3 = UserPortfolioState(
        available_cash=2000.0,
        user_id="user_003",
        broker_type="coinbase",
        min_reserve_pct=0.10
    )
    user3.add_position("SOL-USD", 50, 100, 110)  # $5,500 position
    user3.add_position("ADA-USD", 1000, 0.5, 0.52)  # $520 position
    accounts.append(("user_003 (Coinbase)", "User", user3))

    return accounts


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Calculate capital capacity for all accounts (master + users)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Display actual accounts from portfolio manager
  python calculate_all_accounts_capital.py

  # Run with simulated example accounts
  python calculate_all_accounts_capital.py --simulate

  # Use custom max position percentage
  python calculate_all_accounts_capital.py --simulate --max-position-pct 20
        """
    )

    parser.add_argument('--simulate', action='store_true',
                       help='Use simulated example accounts instead of real data')
    parser.add_argument('--max-position-pct', type=float, default=15.0,
                       help='Maximum position size as %% of total equity (default: 15%%)')
    parser.add_argument('--reserve-pct', type=float, default=10.0,
                       help='Minimum reserve percentage to maintain (default: 10%%)')

    args = parser.parse_args()

    print("=" * 80)
    print("NIJA ALL ACCOUNTS CAPITAL CAPACITY CALCULATOR")
    print("=" * 80)

    accounts = []
    account_names = []
    all_breakdowns = []

    if args.simulate:
        print("\n📋 MODE: Simulated Example Accounts")
        accounts = simulate_example_accounts()
    else:
        print("\n📋 MODE: Live Portfolio Data")

        # Get portfolio manager
        portfolio_mgr = get_portfolio_manager()

        # Get master portfolio
        if portfolio_mgr.platform_portfolio:
            accounts.append(("Platform Account", "Master", portfolio_mgr.platform_portfolio))
        else:
            print("\n⚠️  No master portfolio found. Initialize master portfolio first.")

        # Get all user portfolios
        for key, user_portfolio in portfolio_mgr.user_portfolios.items():
            account_name = f"{user_portfolio.user_id} ({user_portfolio.broker_type})"
            accounts.append((account_name, "User", user_portfolio))

        if not accounts:
            print("\n❌ No accounts found in portfolio manager.")
            print("   Run in --simulate mode to see example output.")
            return 1

    # Calculate breakdown for each account
    for account_name, account_type, portfolio in accounts:
        breakdown = portfolio.get_capital_breakdown(
            max_position_pct=args.max_position_pct / 100.0,
            min_reserve_pct=args.reserve_pct / 100.0
        )

        account_names.append(account_name)
        all_breakdowns.append(breakdown)

        print_account_summary(account_name, breakdown, account_type)

    # Print aggregate summary
    if all_breakdowns:
        print_aggregate_summary(all_breakdowns, account_names)

    print("\n✅ Calculation complete for all accounts\n")

    return 0


if __name__ == '__main__':
    sys.exit(main())
