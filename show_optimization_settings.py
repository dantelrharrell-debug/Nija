#!/usr/bin/env python3
"""
NIJA Optimization Quick Start
Demonstrates the new optimization features for $25/day target

This script shows:
1. Daily target optimization
2. Exchange-specific risk profiles
3. Multi-exchange capital allocation

Usage: python3 show_optimization_settings.py [balance]
Example: python3 show_optimization_settings.py 200

Author: NIJA Trading Systems
Date: December 30, 2025
"""

import sys
import os

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from daily_target_config import print_daily_target_summary
from exchange_risk_profiles import compare_exchange_profiles, get_best_exchange_for_balance
from multi_exchange_allocator import print_allocation_comparison


def show_optimization(account_balance: float, 
                     available_exchanges=None):
    """
    Display complete optimization analysis for account.
    
    Args:
        account_balance: Current account balance
        available_exchanges: List of available exchanges
    """
    if available_exchanges is None:
        available_exchanges = ['coinbase', 'okx', 'kraken']
    
    print("\n" + "="*80)
    print(f"NIJA OPTIMIZATION ANALYSIS FOR ${account_balance:.2f} ACCOUNT")
    print("="*80)
    
    # 1. Daily Target Optimization
    print("\n" + "─"*80)
    print("1️⃣  DAILY PROFIT TARGET OPTIMIZATION")
    print("─"*80)
    print_daily_target_summary(account_balance)
    
    # 2. Exchange Profiles
    print("\n" + "─"*80)
    print("2️⃣  EXCHANGE-SPECIFIC RISK PROFILES")
    print("─"*80)
    compare_exchange_profiles()
    
    # Get best exchange for this balance
    best = get_best_exchange_for_balance(account_balance, available_exchanges)
    print(f"\n💡 RECOMMENDED PRIMARY EXCHANGE FOR ${account_balance:.2f}: {best.upper()}")
    
    # 3. Capital Allocation
    if len(available_exchanges) > 1:
        print("\n" + "─"*80)
        print("3️⃣  MULTI-EXCHANGE CAPITAL ALLOCATION")
        print("─"*80)
        print_allocation_comparison(account_balance, available_exchanges)
    
    # Summary
    print("\n" + "="*80)
    print("SUMMARY & RECOMMENDATIONS")
    print("="*80)
    
    if account_balance < 50:
        print("\n⚠️  SMALL ACCOUNT ($25-50):")
        print("   • Focus on single exchange (OKX for lowest fees)")
        print("   • Target: $5-12/day (scaled from $25/day)")
        print("   • Need 15-20 trades/day with 60%+ win rate")
        print("   • Recommendation: Compound profits to grow account")
        
    elif account_balance < 100:
        print("\n⚠️  GROWING ACCOUNT ($50-100):")
        print("   • Consider adding second exchange (OKX + Kraken)")
        print("   • Target: $12-25/day")
        print("   • Need 15-20 trades/day")
        print("   • Multi-exchange can smooth drawdowns")
        
    elif account_balance < 500:
        print("\n✅ VIABLE ACCOUNT ($100-500):")
        print("   • Use multi-exchange allocation (OKX 46%, Kraken 31%, Coinbase 23%)")
        print("   • Target: $25/day is achievable with 13-20 trades")
        print("   • Fee savings: 30-50% vs Coinbase-only")
        print("   • Drawdown smoothing: 20-40% reduction")
        
    else:
        print("\n✅✅ STRONG ACCOUNT ($500+):")
        print("   • Multi-exchange allocation highly recommended")
        print("   • Target: $25/day easily achievable with 7-13 trades")
        print("   • Significant fee savings with OKX/Kraken allocation")
        print("   • Smooth equity curve through diversification")
    
    print("\n" + "="*80)
    print("\n💡 NEXT STEPS:")
    print("   1. Review settings above and adjust if needed")
    print("   2. Enable optimization in bot/apex_config.py:")
    print("      - Set DAILY_TARGET['enabled'] = True")
    print("      - Set MULTI_EXCHANGE['enabled'] = True")
    print("      - Set EXCHANGE_PROFILES['use_exchange_profiles'] = True")
    print("   3. Add exchange credentials to .env (if using multiple exchanges)")
    print("   4. Test with paper trading first")
    print("   5. Monitor performance and adjust as needed")
    print("\n📚 Full documentation: OPTIMIZATION_GUIDE.md")
    print("="*80 + "\n")


def main():
    """Main entry point"""
    # Get balance from command line or use default
    if len(sys.argv) > 1:
        try:
            balance = float(sys.argv[1])
        except ValueError:
            print(f"Error: Invalid balance '{sys.argv[1]}'")
            print("Usage: python3 show_optimization_settings.py [balance]")
            sys.exit(1)
    else:
        # Use current balance from README (default)
        balance = 34.54
        print(f"No balance specified, using current account balance: ${balance:.2f}")
    
    # Get exchanges from command line or use defaults
    if len(sys.argv) > 2:
        exchanges = sys.argv[2].split(',')
    else:
        exchanges = ['coinbase', 'okx', 'kraken']
    
    show_optimization(balance, exchanges)


if __name__ == "__main__":
    main()
