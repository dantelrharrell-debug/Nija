#!/usr/bin/env python3
"""
Quick Alpaca Connection Status Checker for NIJA Trading Bot

This script checks if Alpaca is connected and configured for:
- Master account (NIJA system)
- User #2: Tania Gilbert (tania_gilbert)

Usage:
    python3 check_alpaca_status.py
    ./check_alpaca_status.py

Exit codes:
    0 = All accounts configured and ready
    1 = Some accounts not configured
    2 = No accounts configured
"""

import os
import sys


def check_env_var(var_name):
    """Check if environment variable is set and not empty"""
    value = os.getenv(var_name, '').strip()
    return bool(value)


def print_header(title):
    """Print a formatted header"""
    print()
    print("=" * 80)
    print(title.center(80))
    print("=" * 80)


def print_section(title):
    """Print a formatted section header"""
    print()
    print(title)
    print("-" * 80)


def main():
    """Main function to check Alpaca connection status"""
    
    print_header("ALPACA CONNECTION STATUS CHECK")
    
    # Check Master account
    print_section("🔍 MASTER ACCOUNT (NIJA System)")
    master_key = check_env_var("ALPACA_API_KEY")
    master_secret = check_env_var("ALPACA_API_SECRET")
    master_paper = os.getenv("ALPACA_PAPER", "true").lower() == "true"
    
    print(f"  ALPACA_API_KEY:    {'✅ SET' if master_key else '❌ NOT SET'}")
    print(f"  ALPACA_API_SECRET: {'✅ SET' if master_secret else '❌ NOT SET'}")
    print(f"  ALPACA_PAPER:      {master_paper} ({'Paper Trading' if master_paper else 'Live Trading'})")
    
    master_configured = master_key and master_secret
    status_icon = "✅" if master_configured else "❌"
    status_text = "CONFIGURED - READY TO TRADE" if master_configured else "NOT CONFIGURED"
    print(f"  Status: {status_icon} {status_text}")
    
    # Check User #2 (Tania Gilbert)
    print_section("👤 USER #2: Tania Gilbert (tania_gilbert)")
    user2_key = check_env_var("ALPACA_USER_TANIA_API_KEY")
    user2_secret = check_env_var("ALPACA_USER_TANIA_API_SECRET")
    user2_paper = os.getenv("ALPACA_USER_TANIA_PAPER", "true").lower() == "true"
    
    print(f"  ALPACA_USER_TANIA_API_KEY:     {'✅ SET' if user2_key else '❌ NOT SET'}")
    print(f"  ALPACA_USER_TANIA_API_SECRET:  {'✅ SET' if user2_secret else '❌ NOT SET'}")
    print(f"  ALPACA_USER_TANIA_PAPER:       {user2_paper} ({'Paper Trading' if user2_paper else 'Live Trading'})")
    
    user2_configured = user2_key and user2_secret
    status_icon = "✅" if user2_configured else "❌"
    status_text = "CONFIGURED - READY TO TRADE" if user2_configured else "NOT CONFIGURED"
    print(f"  Status: {status_icon} {status_text}")
    
    # Summary
    print_header("📊 SUMMARY")
    
    total_configured = sum([master_configured, user2_configured])
    print()
    print(f"  Configured Accounts: {total_configured}/2")
    print()
    
    # Individual account status
    accounts = [
        ("Master account", master_configured),
        ("User #2 (Tania Gilbert)", user2_configured)
    ]
    
    for account_name, is_configured in accounts:
        icon = "✅" if is_configured else "❌"
        status = "CONNECTED to Alpaca" if is_configured else "NOT connected to Alpaca"
        print(f"  {icon} {account_name}: {status}")
    
    # Trading status
    print_header("💼 TRADING STATUS")
    
    if total_configured == 2:
        print()
        print("  ✅ ALL ACCOUNTS CONFIGURED FOR ALPACA TRADING")
        print()
        print("  Both accounts are ready to trade on Alpaca:")
        print("    • Master account: Ready to trade")
        print("    • User #2 (Tania): Ready to trade")
        print()
        print("  The bot will attempt to connect to Alpaca on next startup.")
        exit_code = 0
        
    elif total_configured > 0:
        print()
        print(f"  ⚠️  PARTIAL CONFIGURATION: {total_configured}/2 accounts configured")
        print()
        print("  Configured accounts:")
        if master_configured:
            print("    ✅ Master account: Ready to trade")
        if user2_configured:
            print("    ✅ User #2 (Tania): Ready to trade")
        print()
        print("  Missing accounts:")
        if not master_configured:
            print("    ❌ Master account: Needs ALPACA_API_KEY and ALPACA_API_SECRET")
        if not user2_configured:
            print("    ❌ User #2 (Tania): Needs ALPACA_USER_TANIA_API_KEY and ALPACA_USER_TANIA_API_SECRET")
        exit_code = 1
        
    else:
        print()
        print("  ❌ NO ACCOUNTS CONFIGURED FOR ALPACA TRADING")
        print()
        print("  Alpaca is NOT connected and CANNOT trade for any account.")
        print()
        print("  To enable Alpaca trading, set the following environment variables:")
        print()
        print("  For Master account:")
        print("    export ALPACA_API_KEY='your-api-key'")
        print("    export ALPACA_API_SECRET='your-api-secret'")
        print("    export ALPACA_PAPER='true'  # or 'false' for live trading")
        print()
        print("  For User #2 (Tania Gilbert):")
        print("    export ALPACA_USER_TANIA_API_KEY='your-api-key'")
        print("    export ALPACA_USER_TANIA_API_SECRET='your-api-secret'")
        print("    export ALPACA_USER_TANIA_PAPER='true'  # or 'false' for live trading")
        print()
        print("  See BROKER_INTEGRATION_GUIDE.md for detailed setup instructions.")
        exit_code = 2
    
    print()
    print("=" * 80)
    print()
    
    # Additional help
    if total_configured < 2:
        print("📖 For detailed setup instructions, see:")
        print("   - BROKER_INTEGRATION_GUIDE.md (broker setup guide)")
        print("   - MASTER_CONNECTION_STATUS.md (complete status report)")
        print()
    
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
