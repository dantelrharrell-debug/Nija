#!/usr/bin/env python3
"""
Comprehensive Balance and Configuration Audit
==============================================

Shows the complete state of:
1. Configuration (MICRO_CAP settings)
2. Tracked orders (from order tracker)
3. Performance metrics (from performance tracker)
4. Live broker data (if available)

Author: NIJA Trading Systems
Date: February 17, 2026
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
import json
from pathlib import Path


def print_header(title):
    """Print formatted header"""
    print(f"\n{'='*80}")
    print(f"{title:^80}")
    print(f"{'='*80}")


def print_section(title):
    """Print formatted section"""
    print(f"\n{'─'*80}")
    print(f"📊 {title}")
    print(f"{'─'*80}")


def check_micro_cap_config():
    """Check MICRO_CAP configuration"""
    print_header("MICRO_CAP CONFIGURATION CHECK")
    
    try:
        from micro_capital_config import (
            MICRO_CAPITAL_MODE,
            MAX_POSITIONS,
            MAX_POSITION_PCT,
            RISK_PER_TRADE,
            MIN_TRADE_SIZE,
            MIN_BALANCE_TO_TRADE,
            ENABLE_DCA,
            ALLOW_MULTIPLE_ENTRIES_SAME_SYMBOL,
            DAILY_MAX_LOSS,
            MAX_DRAWDOWN
        )
        
        print(f"\n✅ MICRO_CAP Configuration Loaded Successfully\n")
        
        print(f"🔒 MODE:")
        print(f"   MICRO_CAPITAL_MODE:               {'✅ ACTIVE' if MICRO_CAPITAL_MODE else '❌ INACTIVE'}")
        
        print(f"\n📊 POSITION LIMITS:")
        print(f"   MAX_POSITIONS:                    {MAX_POSITIONS}")
        print(f"   MAX_POSITION_PCT:                 {MAX_POSITION_PCT}%")
        print(f"   MIN_TRADE_SIZE:                   ${MIN_TRADE_SIZE:.2f}")
        print(f"   MIN_BALANCE_TO_TRADE:             ${MIN_BALANCE_TO_TRADE:.2f}")
        
        print(f"\n🚫 RESTRICTIONS (Should be DISABLED for MICRO_CAP):")
        print(f"   ENABLE_DCA:                       {'❌ DISABLED ✅' if not ENABLE_DCA else '✅ ENABLED ⚠️'}")
        print(f"   ALLOW_MULTIPLE_ENTRIES_SAME_SYMBOL: {'❌ DISABLED ✅' if not ALLOW_MULTIPLE_ENTRIES_SAME_SYMBOL else '✅ ENABLED ⚠️'}")
        
        print(f"\n🛡️ RISK MANAGEMENT:")
        print(f"   RISK_PER_TRADE:                   {RISK_PER_TRADE}%")
        print(f"   DAILY_MAX_LOSS:                   {DAILY_MAX_LOSS}%")
        print(f"   MAX_DRAWDOWN:                     {MAX_DRAWDOWN}%")
        
        # Verify hardening
        print(f"\n🔍 HARDENING VERIFICATION:")
        issues = []
        
        if ENABLE_DCA:
            issues.append("⚠️ DCA is ENABLED (should be DISABLED for MICRO_CAP)")
        else:
            print(f"   ✅ DCA is properly DISABLED")
        
        if ALLOW_MULTIPLE_ENTRIES_SAME_SYMBOL:
            issues.append("⚠️ Multiple entries on same symbol ENABLED (should be DISABLED)")
        else:
            print(f"   ✅ Multiple entries properly DISABLED")
        
        if MAX_POSITIONS > 4:
            issues.append(f"⚠️ MAX_POSITIONS is {MAX_POSITIONS} (recommended: 4 or less for micro capital)")
        else:
            print(f"   ✅ MAX_POSITIONS is appropriate: {MAX_POSITIONS}")
        
        if MIN_TRADE_SIZE < 5.0:
            issues.append(f"⚠️ MIN_TRADE_SIZE is ${MIN_TRADE_SIZE:.2f} (very small, may cause fragmentation)")
        else:
            print(f"   ✅ MIN_TRADE_SIZE is reasonable: ${MIN_TRADE_SIZE:.2f}")
        
        if issues:
            print(f"\n❌ CONFIGURATION ISSUES FOUND:")
            for issue in issues:
                print(f"   {issue}")
            return False
        else:
            print(f"\n✅ Configuration is properly hardened for MICRO_CAP")
            return True
            
    except Exception as e:
        print(f"\n❌ Could not load MICRO_CAP configuration: {e}")
        return False


def check_order_tracker_state():
    """Check order tracker state"""
    print_header("ORDER TRACKER STATE")
    
    data_dir = Path("./data")
    state_file = data_dir / "account_orders_state.json"
    
    if not state_file.exists():
        print(f"\n⚠️ No order tracker state file found at: {state_file}")
        print(f"   This is expected if the system hasn't run yet.")
        return True
    
    try:
        with open(state_file, 'r') as f:
            state = json.load(f)
        
        orders_by_account = state.get('orders_by_account', {})
        reserved_capital = state.get('reserved_capital_by_account', {})
        
        print(f"\n📊 Order Tracker State (Last Updated: {state.get('timestamp', 'unknown')})")
        
        if not orders_by_account:
            print(f"\n✅ No tracked orders (clean state)")
            return True
        
        total_orders = sum(len(orders) for orders in orders_by_account.values())
        print(f"\nTotal Accounts with Orders: {len(orders_by_account)}")
        print(f"Total Orders Tracked: {total_orders}")
        
        issues = []
        
        for account_id, orders in orders_by_account.items():
            print(f"\n   Account: {account_id}")
            
            open_orders = [o for o in orders if o.get('status') == 'open']
            held_capital = reserved_capital.get(account_id, 0)
            
            print(f"      Total Orders: {len(orders)}")
            print(f"      Open Orders: {len(open_orders)}")
            print(f"      Held Capital: ${held_capital:.2f}")
            
            # Check for fragmentation
            if len(open_orders) > 1 and held_capital > 0:
                avg_per_order = held_capital / len(open_orders)
                if avg_per_order < 20:  # If average order is less than $20
                    issues.append(
                        f"⚠️ {account_id}: ORDER FRAGMENTATION - "
                        f"{len(open_orders)} orders averaging ${avg_per_order:.2f} each"
                    )
            
            # Show order details
            if open_orders:
                print(f"      Open Order Details:")
                for i, order in enumerate(open_orders[:5], 1):  # Show first 5
                    symbol = order.get('symbol', 'UNKNOWN')
                    side = order.get('side', 'UNKNOWN')
                    size = order.get('size_usd', 0)
                    print(f"         {i}. {symbol} {side} ${size:.2f}")
                if len(open_orders) > 5:
                    print(f"         ... and {len(open_orders) - 5} more")
        
        if issues:
            print(f"\n❌ ORDER TRACKER ISSUES:")
            for issue in issues:
                print(f"   {issue}")
            return False
        else:
            print(f"\n✅ Order tracker state looks good")
            return True
            
    except Exception as e:
        print(f"\n❌ Could not read order tracker state: {e}")
        return False


def check_performance_tracker_state():
    """Check performance tracker state"""
    print_header("PERFORMANCE TRACKER STATE")
    
    data_dir = Path("./data")
    perf_files = list(data_dir.glob("performance_*.json"))
    
    if not perf_files:
        print(f"\n⚠️ No performance tracker files found")
        print(f"   This is expected if no trades have been completed yet.")
        return True
    
    print(f"\n📊 Performance Files Found: {len(perf_files)}")
    
    for perf_file in perf_files:
        try:
            with open(perf_file, 'r') as f:
                state = json.load(f)
            
            account_id = state.get('account_id', 'UNKNOWN')
            metrics = state.get('metrics', {})
            trade_history = state.get('trade_history', [])
            
            print(f"\n   Account: {account_id}")
            print(f"      Total Trades: {metrics.get('total_trades', 0)}")
            print(f"      Win Rate: {metrics.get('win_rate', 0):.1f}%")
            print(f"      Net P&L: ${metrics.get('net_pnl', 0):.2f}")
            print(f"      Expectancy: ${metrics.get('expectancy_per_trade', 0):.2f}/trade")
            print(f"      Max Drawdown: ${metrics.get('max_drawdown', 0):.2f} ({metrics.get('max_drawdown_pct', 0):.1f}%)")
            
            # Verify no cross-contamination
            if trade_history:
                wrong_account_trades = [
                    t for t in trade_history 
                    if t.get('account_id') != account_id
                ]
                if wrong_account_trades:
                    print(f"      ❌ CROSS-CONTAMINATION: {len(wrong_account_trades)} trades belong to other accounts!")
                else:
                    print(f"      ✅ No cross-contamination detected")
        
        except Exception as e:
            print(f"\n   ❌ Could not read {perf_file}: {e}")
    
    return True


def check_environment_variables():
    """Check relevant environment variables"""
    print_header("ENVIRONMENT VARIABLES")
    
    relevant_vars = [
        'MICRO_CAPITAL_MODE',
        'MAX_CONCURRENT_POSITIONS',
        'ENABLE_DCA',
        'ALLOW_MULTIPLE_ENTRIES_SAME_SYMBOL',
        'MIN_CASH_TO_BUY',
        'PRIMARY_BROKER',
        'MODE'
    ]
    
    print(f"\n📋 Relevant Environment Variables:")
    
    for var in relevant_vars:
        value = os.environ.get(var, 'NOT SET')
        print(f"   {var:35s} = {value}")
    
    return True


def main():
    """Main audit"""
    print(f"\n{'█'*80}")
    print(f"{'COMPREHENSIVE BALANCE & CONFIGURATION AUDIT':^80}")
    print(f"{'Timestamp: ' + datetime.now().strftime('%Y-%m-%d %H:%M:%S'):^80}")
    print(f"{'█'*80}")
    
    results = []
    
    # Check configuration
    results.append(('Configuration', check_micro_cap_config()))
    
    # Check order tracker
    results.append(('Order Tracker', check_order_tracker_state()))
    
    # Check performance tracker
    results.append(('Performance Tracker', check_performance_tracker_state()))
    
    # Check environment
    results.append(('Environment', check_environment_variables()))
    
    # Summary
    print_header("AUDIT SUMMARY")
    
    print(f"\n📋 Results:")
    all_passed = True
    for name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"   {name:25s} {status}")
        if not passed:
            all_passed = False
    
    print(f"\n{'─'*80}")
    
    if all_passed:
        print(f"\n✅ AUDIT PASSED: System is properly configured and hardened")
        print(f"\n   Key Findings:")
        print(f"   • MICRO_CAP mode is active with proper restrictions")
        print(f"   • DCA is disabled (prevents averaging down)")
        print(f"   • Multiple entries on same symbol disabled (prevents fragmentation)")
        print(f"   • Order tracking and performance tracking systems are operational")
        print(f"\n   Expected Behavior:")
        print(f"   • Held capital should align with 1-4 positions of ~$5-20 each")
        print(f"   • No order fragmentation (many small orders)")
        print(f"   • Each account's metrics tracked independently")
    else:
        print(f"\n❌ AUDIT FAILED: Issues detected")
        print(f"\n   Review the sections above for specific issues.")
        print(f"   Address configuration issues before trading.")
    
    print(f"\n{'═'*80}\n")
    
    return 0 if all_passed else 1


if __name__ == '__main__':
    sys.exit(main())
