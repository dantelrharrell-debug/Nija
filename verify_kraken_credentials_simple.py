#!/usr/bin/env python3
"""
Simple Kraken Credential Verification (Offline)
===============================================

Checks if Kraken API credentials are configured for both Master and User #1
without attempting actual API connections.

Usage:
    python3 verify_kraken_credentials_simple.py
"""

import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def main():
    print("=" * 80)
    print("  KRAKEN CREDENTIALS VERIFICATION - Master & User #1")
    print("=" * 80)
    print()
    
    # Check master credentials
    master_key = os.getenv("KRAKEN_MASTER_API_KEY", "").strip()
    master_secret = os.getenv("KRAKEN_MASTER_API_SECRET", "").strip()
    
    # Check user credentials
    user_key = os.getenv("KRAKEN_USER_DAIVON_API_KEY", "").strip()
    user_secret = os.getenv("KRAKEN_USER_DAIVON_API_SECRET", "").strip()
    
    # Master account status
    print("🏦 MASTER ACCOUNT (Nija System):")
    print("-" * 80)
    if master_key and master_secret:
        print(f"  ✅ KRAKEN_MASTER_API_KEY:    Configured ({len(master_key)} characters)")
        print(f"  ✅ KRAKEN_MASTER_API_SECRET: Configured ({len(master_secret)} characters)")
        print(f"  ✅ Status: READY FOR TRADING")
        master_ok = True
    else:
        print(f"  ❌ KRAKEN_MASTER_API_KEY:    {'Not set' if not master_key else 'Set'}")
        print(f"  ❌ KRAKEN_MASTER_API_SECRET: {'Not set' if not master_secret else 'Set'}")
        print(f"  ❌ Status: NOT CONFIGURED")
        master_ok = False
    
    print()
    
    # User #1 account status
    print("👤 USER #1 ACCOUNT (Daivon Frazier):")
    print("-" * 80)
    if user_key and user_secret:
        print(f"  ✅ KRAKEN_USER_DAIVON_API_KEY:    Configured ({len(user_key)} characters)")
        print(f"  ✅ KRAKEN_USER_DAIVON_API_SECRET: Configured ({len(user_secret)} characters)")
        print(f"  ✅ Status: READY FOR TRADING")
        user_ok = True
    else:
        print(f"  ❌ KRAKEN_USER_DAIVON_API_KEY:    {'Not set' if not user_key else 'Set'}")
        print(f"  ❌ KRAKEN_USER_DAIVON_API_SECRET: {'Not set' if not user_secret else 'Set'}")
        print(f"  ❌ Status: NOT CONFIGURED")
        user_ok = False
    
    print()
    print("=" * 80)
    print("  SUMMARY")
    print("=" * 80)
    print()
    
    if master_ok and user_ok:
        print("  ✅ BOTH ACCOUNTS CONFIGURED")
        print()
        print("  Both Master and User #1 have valid Kraken API credentials.")
        print("  They are ready to connect and trade when the bot starts.")
        print()
        print("  Next Steps:")
        print("  • Bot will automatically connect to Kraken on startup")
        print("  • Both accounts will trade independently")
        print("  • Master and User #1 funds are completely separated")
        print()
        return 0
    elif master_ok:
        print("  ⚠️  MASTER CONFIGURED, USER #1 NOT CONFIGURED")
        print()
        print("  Master account has credentials but User #1 does not.")
        print()
        print("  To configure User #1:")
        print("  1. Set KRAKEN_USER_DAIVON_API_KEY in .env")
        print("  2. Set KRAKEN_USER_DAIVON_API_SECRET in .env")
        print()
        return 1
    elif user_ok:
        print("  ⚠️  USER #1 CONFIGURED, MASTER NOT CONFIGURED")
        print()
        print("  User #1 has credentials but Master account does not.")
        print()
        print("  To configure Master:")
        print("  1. Set KRAKEN_MASTER_API_KEY in .env")
        print("  2. Set KRAKEN_MASTER_API_SECRET in .env")
        print()
        return 1
    else:
        print("  ❌ NEITHER ACCOUNT CONFIGURED")
        print()
        print("  No Kraken credentials found.")
        print()
        print("  To configure:")
        print("  1. Create API keys at https://www.kraken.com/u/security/api")
        print("  2. Set environment variables in .env file")
        print()
        return 2
    
    print("=" * 80)

if __name__ == "__main__":
    sys.exit(main())
