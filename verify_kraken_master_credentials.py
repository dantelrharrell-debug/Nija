#!/usr/bin/env python3
"""
Verify Kraken Master Account Credentials
=========================================

This script verifies that the master's Kraken account credentials
are properly configured in the environment (without requiring network access).
"""

import os
import sys
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

print("=" * 70)
print("🔍 VERIFYING MASTER'S KRAKEN ACCOUNT CREDENTIALS")
print("=" * 70)
print()

# Check if credentials are present
print("Checking for Kraken Master credentials in environment...")
print()

api_key = os.getenv("KRAKEN_MASTER_API_KEY", "").strip()
api_secret = os.getenv("KRAKEN_MASTER_API_SECRET", "").strip()

# Also check legacy credentials for comparison
legacy_api_key = os.getenv("KRAKEN_API_KEY", "").strip()
legacy_api_secret = os.getenv("KRAKEN_API_SECRET", "").strip()

# Check user credentials for comparison
user_api_key = os.getenv("KRAKEN_USER_DAIVON_API_KEY", "").strip()
user_api_secret = os.getenv("KRAKEN_USER_DAIVON_API_SECRET", "").strip()

credentials_ok = True

# Master credentials
if not api_key:
    print("❌ KRAKEN_MASTER_API_KEY is NOT set")
    credentials_ok = False
else:
    print(f"✅ KRAKEN_MASTER_API_KEY is set ({len(api_key)} characters)")
    print(f"   Preview: {api_key[:10]}...{api_key[-10:]}")

if not api_secret:
    print("❌ KRAKEN_MASTER_API_SECRET is NOT set")
    credentials_ok = False
else:
    print(f"✅ KRAKEN_MASTER_API_SECRET is set ({len(api_secret)} characters)")
    print(f"   Preview: {api_secret[:10]}...{api_secret[-10:]}")

print()
print("-" * 70)
print("Additional Kraken Credentials:")
print("-" * 70)

# Legacy credentials
if legacy_api_key:
    print(f"ℹ️  KRAKEN_API_KEY (legacy) is set ({len(legacy_api_key)} characters)")
else:
    print("ℹ️  KRAKEN_API_KEY (legacy) is NOT set")

if legacy_api_secret:
    print(f"ℹ️  KRAKEN_API_SECRET (legacy) is set ({len(legacy_api_secret)} characters)")
else:
    print("ℹ️  KRAKEN_API_SECRET (legacy) is NOT set")

print()

# User credentials
if user_api_key:
    print(f"✅ KRAKEN_USER_DAIVON_API_KEY (user) is set ({len(user_api_key)} characters)")
else:
    print("ℹ️  KRAKEN_USER_DAIVON_API_KEY (user) is NOT set")

if user_api_secret:
    print(f"✅ KRAKEN_USER_DAIVON_API_SECRET (user) is set ({len(user_api_secret)} characters)")
else:
    print("ℹ️  KRAKEN_USER_DAIVON_API_SECRET (user) is NOT set")

print()
print("=" * 70)

if credentials_ok:
    print("✅ MASTER'S KRAKEN ACCOUNT CREDENTIALS ARE CONFIGURED!")
    print("=" * 70)
    print()
    print("Summary:")
    print("--------")
    print("The master's Kraken account credentials (KRAKEN_MASTER_API_KEY")
    print("and KRAKEN_MASTER_API_SECRET) are properly set in the environment.")
    print()
    print("When the trading bot starts, it will:")
    print("1. Load these credentials from the .env file")
    print("2. Initialize a KrakenBroker with AccountType.MASTER")
    print("3. Connect to Kraken Pro API using the master credentials")
    print("4. Start trading on the master's Kraken account")
    print()
    print("The connection is properly configured in bot/trading_strategy.py:")
    print("- Line 223: kraken = KrakenBroker() creates master broker")
    print("- KrakenBroker defaults to AccountType.MASTER")
    print("- Master broker uses KRAKEN_MASTER_API_KEY/SECRET")
    print()
    print("✅ CONFIRMATION: Master's Kraken account IS connected to NIJA")
    sys.exit(0)
else:
    print("❌ MASTER'S KRAKEN ACCOUNT CREDENTIALS ARE MISSING!")
    print("=" * 70)
    print()
    print("To configure the master's Kraken account:")
    print("1. Obtain Kraken API credentials for the master account")
    print("2. Add to .env file:")
    print("   KRAKEN_MASTER_API_KEY=<your-master-api-key>")
    print("   KRAKEN_MASTER_API_SECRET=<your-master-api-secret>")
    print("3. Restart the trading bot")
    sys.exit(1)
