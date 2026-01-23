#!/usr/bin/env python3
"""
Show User Account Balances
===========================

Displays current balances for all user accounts in a clear, formatted table.

Usage:
    python scripts/show_user_balances.py
    python scripts/show_user_balances.py --json  # Output as JSON
"""

import sys
import os
import json
import argparse
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.multi_account_broker_manager import multi_account_broker_manager


def format_currency(amount: float) -> str:
    """Format amount as currency with color coding"""
    return f"${amount:,.2f}"


def show_balances_table():
    """Display balances in a formatted table"""
    print("\n" + "=" * 80)
    print("NIJA USER ACCOUNT BALANCES")
    print("=" * 80)
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    
    # CRITICAL FIX: Connect users from config before displaying balances
    # This ensures user accounts are loaded and visible
    print("\n🔄 Loading user accounts from configuration...")
    multi_account_broker_manager.connect_users_from_config()
    print("")
    
    # Get all balances
    balances = multi_account_broker_manager.get_all_balances()
    
    # Display master account
    print("\n🔷 MASTER ACCOUNT (Nija System)")
    print("-" * 80)
    master_balances = balances.get('master', {})
    if master_balances:
        master_total = 0.0
        for broker, balance in master_balances.items():
            print(f"   {broker.upper():15} {format_currency(balance):>15}")
            master_total += balance
        print("-" * 80)
        print(f"   {'TOTAL':15} {format_currency(master_total):>15}")
    else:
        print("   No master brokers connected")
    
    # Display user accounts
    print("\n🔷 USER ACCOUNTS")
    print("-" * 80)
    user_balances = balances.get('users', {})
    
    if user_balances:
        # Calculate totals
        grand_total = 0.0
        user_count = len(user_balances)
        
        for user_id, brokers in user_balances.items():
            print(f"\n   👤 User: {user_id}")
            print("   " + "-" * 76)
            
            user_total = 0.0
            if brokers:
                for broker, balance in brokers.items():
                    # Show balance, even if $0.00 (indicates disconnected but configured broker)
                    print(f"      {broker.upper():13} {format_currency(balance):>15}")
                    user_total += balance
                print("   " + "-" * 76)
                print(f"      {'SUBTOTAL':13} {format_currency(user_total):>15}")
            else:
                print("      No brokers connected")
            
            grand_total += user_total
        
        # Summary
        print("\n" + "=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print(f"   Total Users:           {user_count}")
        print(f"   Total User Capital:    {format_currency(grand_total)}")
        if user_count > 0:
            avg_balance = grand_total / user_count
            print(f"   Average per User:      {format_currency(avg_balance)}")
        print("=" * 80)
    else:
        print("   No user accounts found")
        print("=" * 80)
    
    print()


def show_balances_json():
    """Display balances as JSON"""
    # CRITICAL FIX: Connect users from config before displaying balances
    # This ensures user accounts are loaded and visible
    multi_account_broker_manager.connect_users_from_config()
    
    balances = multi_account_broker_manager.get_all_balances()
    
    # Add metadata
    output = {
        'timestamp': datetime.now().isoformat(),
        'balances': balances
    }
    
    # Calculate totals
    master_total = sum(balances.get('master', {}).values())
    user_totals = {}
    grand_total = 0.0
    
    for user_id, brokers in balances.get('users', {}).items():
        user_total = sum(brokers.values())
        user_totals[user_id] = user_total
        grand_total += user_total
    
    output['summary'] = {
        'master_total': master_total,
        'user_totals': user_totals,
        'total_user_capital': grand_total,
        'user_count': len(user_totals),
        'average_per_user': grand_total / len(user_totals) if user_totals else 0
    }
    
    print(json.dumps(output, indent=2))


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Display current balances for all user accounts'
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output as JSON instead of formatted table'
    )
    
    args = parser.parse_args()
    
    try:
        if args.json:
            show_balances_json()
        else:
            show_balances_table()
        return 0
    except Exception as e:
        print(f"\n❌ Error displaying balances: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    exit(main())
