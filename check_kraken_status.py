#!/usr/bin/env python3
"""
Quick Kraken Connection Status Checker for NIJA Trading Bot

This script checks if Kraken is connected and configured for:
- Master account (NIJA system)
- User #1: Daivon Frazier (daivon_frazier)
- User #2: Tania Gilbert (tania_gilbert)

Usage:
    python3 check_kraken_status.py
    ./check_kraken_status.py

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
    """Main function to check Kraken connection status"""
    
    print_header("KRAKEN CONNECTION STATUS CHECK")
    
    # Check Master account
    print_section("🔍 MASTER ACCOUNT (NIJA System)")
    master_key = check_env_var("KRAKEN_MASTER_API_KEY")
    master_secret = check_env_var("KRAKEN_MASTER_API_SECRET")
    
    print(f"  KRAKEN_MASTER_API_KEY:    {'✅ SET' if master_key else '❌ NOT SET'}")
    print(f"  KRAKEN_MASTER_API_SECRET: {'✅ SET' if master_secret else '❌ NOT SET'}")
    
    master_configured = master_key and master_secret
    status_icon = "✅" if master_configured else "❌"
    status_text = "CONFIGURED - READY TO TRADE" if master_configured else "NOT CONFIGURED"
    print(f"  Status: {status_icon} {status_text}")
    
    # Check User #1 (Daivon Frazier)
    print_section("👤 USER #1: Daivon Frazier (daivon_frazier)")
    user1_key = check_env_var("KRAKEN_USER_DAIVON_API_KEY")
    user1_secret = check_env_var("KRAKEN_USER_DAIVON_API_SECRET")
    
    print(f"  KRAKEN_USER_DAIVON_API_KEY:    {'✅ SET' if user1_key else '❌ NOT SET'}")
    print(f"  KRAKEN_USER_DAIVON_API_SECRET: {'✅ SET' if user1_secret else '❌ NOT SET'}")
    
    user1_configured = user1_key and user1_secret
    status_icon = "✅" if user1_configured else "❌"
    status_text = "CONFIGURED - READY TO TRADE" if user1_configured else "NOT CONFIGURED"
    print(f"  Status: {status_icon} {status_text}")
    
    # Check User #2 (Tania Gilbert)
    print_section("👤 USER #2: Tania Gilbert (tania_gilbert)")
    user2_key = check_env_var("KRAKEN_USER_TANIA_API_KEY")
    user2_secret = check_env_var("KRAKEN_USER_TANIA_API_SECRET")
    
    print(f"  KRAKEN_USER_TANIA_API_KEY:     {'✅ SET' if user2_key else '❌ NOT SET'}")
    print(f"  KRAKEN_USER_TANIA_API_SECRET:  {'✅ SET' if user2_secret else '❌ NOT SET'}")
    
    user2_configured = user2_key and user2_secret
    status_icon = "✅" if user2_configured else "❌"
    status_text = "CONFIGURED - READY TO TRADE" if user2_configured else "NOT CONFIGURED"
    print(f"  Status: {status_icon} {status_text}")
    
    # Summary
    print_header("📊 SUMMARY")
    
    total_configured = sum([master_configured, user1_configured, user2_configured])
    print()
    print(f"  Configured Accounts: {total_configured}/3")
    print()
    
    # Individual account status
    accounts = [
        ("Master account", master_configured),
        ("User #1 (Daivon Frazier)", user1_configured),
        ("User #2 (Tania Gilbert)", user2_configured)
    ]
    
    for account_name, is_configured in accounts:
        icon = "✅" if is_configured else "❌"
        status = "CONNECTED to Kraken" if is_configured else "NOT connected to Kraken"
        print(f"  {icon} {account_name}: {status}")
    
    # Trading status
    print_header("💼 TRADING STATUS")
    
    if total_configured == 3:
        print()
        print("  ✅ ALL ACCOUNTS CONFIGURED FOR KRAKEN TRADING")
        print()
        print("  All three accounts are ready to trade on Kraken:")
        print("    • Master account: Ready to trade")
        print("    • User #1 (Daivon): Ready to trade")
        print("    • User #2 (Tania): Ready to trade")
        print()
        print("  The bot will attempt to connect to Kraken on next startup.")
        exit_code = 0
        
    elif total_configured > 0:
        print()
        print(f"  ⚠️  PARTIAL CONFIGURATION: {total_configured}/3 accounts configured")
        print()
        print("  Configured accounts:")
        if master_configured:
            print("    ✅ Master account: Ready to trade")
        if user1_configured:
            print("    ✅ User #1 (Daivon): Ready to trade")
        if user2_configured:
            print("    ✅ User #2 (Tania): Ready to trade")
        print()
        print("  Missing accounts:")
        if not master_configured:
            print("    ❌ Master account: Needs KRAKEN_MASTER_API_KEY and KRAKEN_MASTER_API_SECRET")
        if not user1_configured:
            print("    ❌ User #1 (Daivon): Needs KRAKEN_USER_DAIVON_API_KEY and KRAKEN_USER_DAIVON_API_SECRET")
        if not user2_configured:
            print("    ❌ User #2 (Tania): Needs KRAKEN_USER_TANIA_API_KEY and KRAKEN_USER_TANIA_API_SECRET")
        exit_code = 1
        
    else:
        print()
        print("  ❌ NO ACCOUNTS CONFIGURED FOR KRAKEN TRADING")
        print()
        print("  Kraken is NOT connected and CANNOT trade for any account.")
        print()
        print("  To enable Kraken trading, set the following environment variables:")
        print()
        print("  For Master account:")
        print("    export KRAKEN_MASTER_API_KEY='your-api-key'")
        print("    export KRAKEN_MASTER_API_SECRET='your-api-secret'")
        print()
        print("  For User #1 (Daivon Frazier):")
        print("    export KRAKEN_USER_DAIVON_API_KEY='your-api-key'")
        print("    export KRAKEN_USER_DAIVON_API_SECRET='your-api-secret'")
        print()
        print("  For User #2 (Tania Gilbert):")
        print("    export KRAKEN_USER_TANIA_API_KEY='your-api-key'")
        print("    export KRAKEN_USER_TANIA_API_SECRET='your-api-secret'")
        print()
        print("  See KRAKEN_CONNECTION_STATUS.md for detailed setup instructions.")
        exit_code = 2
    
    print()
    print("=" * 80)
    print()
    
    # Additional help
    if total_configured < 3:
        print("📖 For detailed setup instructions, see:")
        print("   - KRAKEN_CONNECTION_STATUS.md (complete status report)")
        print("   - MULTI_USER_SETUP_GUIDE.md (user setup guide)")
        print("   - KRAKEN_NONCE_IMPROVEMENTS.md (technical details)")
        print()
    
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
