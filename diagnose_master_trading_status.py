#!/usr/bin/env python3
"""
Diagnostic script to check why Masters accounts (Alpaca, Kraken, Coinbase) are not trading.
This script checks credentials, connections, and trading status for all master brokers.
"""

import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

print("=" * 80)
print("NIJA MASTERS TRADING STATUS DIAGNOSTIC")
print("=" * 80)
print()

# Check if we're in the correct directory
if not os.path.exists('bot'):
    print("❌ ERROR: 'bot' directory not found!")
    print("   Please run this script from the Nija root directory.")
    sys.exit(1)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

print("📋 STEP 1: Checking Environment Variables")
print("-" * 80)

# Check Coinbase credentials
coinbase_key = os.getenv("COINBASE_API_KEY", "")
coinbase_secret = os.getenv("COINBASE_API_SECRET", "")
print(f"✓ COINBASE_API_KEY: {'✅ SET' if coinbase_key else '❌ NOT SET'} ({len(coinbase_key)} chars)")
print(f"✓ COINBASE_API_SECRET: {'✅ SET' if coinbase_secret else '❌ NOT SET'} ({len(coinbase_secret)} chars)")

# Check Kraken MASTER credentials
kraken_master_key = os.getenv("KRAKEN_MASTER_API_KEY", "")
kraken_master_secret = os.getenv("KRAKEN_MASTER_API_SECRET", "")
print(f"✓ KRAKEN_MASTER_API_KEY: {'✅ SET' if kraken_master_key else '❌ NOT SET'} ({len(kraken_master_key)} chars)")
print(f"✓ KRAKEN_MASTER_API_SECRET: {'✅ SET' if kraken_master_secret else '❌ NOT SET'} ({len(kraken_master_secret)} chars)")

# Check Alpaca credentials
alpaca_key = os.getenv("ALPACA_API_KEY", "")
alpaca_secret = os.getenv("ALPACA_API_SECRET", "")
alpaca_paper = os.getenv("ALPACA_PAPER", "true")
alpaca_base_url = os.getenv("ALPACA_BASE_URL", "")
print(f"✓ ALPACA_API_KEY: {'✅ SET' if alpaca_key else '❌ NOT SET'} ({len(alpaca_key)} chars)")
print(f"✓ ALPACA_API_SECRET: {'✅ SET' if alpaca_secret else '❌ NOT SET'} ({len(alpaca_secret)} chars)")
print(f"✓ ALPACA_PAPER: {alpaca_paper}")
print(f"✓ ALPACA_BASE_URL: {alpaca_base_url if alpaca_base_url else '❌ NOT SET'}")

print()
print("📋 STEP 2: Checking Python Dependencies")
print("-" * 80)

# Check Coinbase SDK
try:
    from coinbase.rest import RESTClient
    print("✅ Coinbase SDK (coinbase.rest) installed")
except ImportError as e:
    print(f"❌ Coinbase SDK NOT installed: {e}")
    print("   Install: pip install coinbase-advanced-py")

# Check Kraken SDK
try:
    import krakenex
    from pykrakenapi import KrakenAPI
    print("✅ Kraken SDK (krakenex, pykrakenapi) installed")
except ImportError as e:
    print(f"❌ Kraken SDK NOT installed: {e}")
    print("   Install: pip install krakenex pykrakenapi")

# Check Alpaca SDK
try:
    from alpaca.trading.client import TradingClient
    print("✅ Alpaca SDK (alpaca-py) installed")
except ImportError as e:
    print(f"❌ Alpaca SDK NOT installed: {e}")
    print("   Install: pip install alpaca-py")

print()
print("📋 STEP 3: Testing Broker Connections")
print("-" * 80)

# Test Coinbase connection
print("\n🔵 Testing COINBASE MASTER connection...")
if coinbase_key and coinbase_secret:
    try:
        from broker_manager import CoinbaseBroker, AccountType
        coinbase_broker = CoinbaseBroker()
        if coinbase_broker.connect():
            print("   ✅ Coinbase MASTER connected successfully")
            try:
                balance = coinbase_broker.get_account_balance()
                print(f"   💰 Balance: ${balance:,.2f}")
            except Exception as bal_err:
                print(f"   ⚠️  Could not get balance: {bal_err}")
        else:
            print("   ❌ Coinbase MASTER connection failed")
    except Exception as e:
        print(f"   ❌ Coinbase MASTER error: {e}")
        import traceback
        traceback.print_exc()
else:
    print("   ⏭️  Skipped (credentials not set)")

# Test Kraken MASTER connection
print("\n🟣 Testing KRAKEN MASTER connection...")
if kraken_master_key and kraken_master_secret:
    try:
        from broker_manager import KrakenBroker, AccountType
        kraken_broker = KrakenBroker(account_type=AccountType.MASTER)
        if kraken_broker.connect():
            print("   ✅ Kraken MASTER connected successfully")
            try:
                balance = kraken_broker.get_account_balance()
                print(f"   💰 Balance: ${balance:,.2f}")
            except Exception as bal_err:
                print(f"   ⚠️  Could not get balance: {bal_err}")
        else:
            print("   ❌ Kraken MASTER connection failed")
    except Exception as e:
        print(f"   ❌ Kraken MASTER error: {e}")
        import traceback
        traceback.print_exc()
else:
    print("   ⏭️  Skipped (credentials not set)")

# Test Alpaca connection
print("\n🟡 Testing ALPACA connection...")
if alpaca_key and alpaca_secret:
    try:
        from broker_manager import AlpacaBroker
        alpaca_broker = AlpacaBroker()
        if alpaca_broker.connect():
            print(f"   ✅ Alpaca connected successfully ({'PAPER' if alpaca_paper.lower() == 'true' else 'LIVE'} mode)")
            try:
                balance = alpaca_broker.get_account_balance()
                print(f"   💰 Balance: ${balance:,.2f}")
            except Exception as bal_err:
                print(f"   ⚠️  Could not get balance: {bal_err}")
        else:
            print("   ❌ Alpaca connection failed")
    except Exception as e:
        print(f"   ❌ Alpaca error: {e}")
        import traceback
        traceback.print_exc()
else:
    print("   ⏭️  Skipped (credentials not set)")

print()
print("📋 STEP 4: Checking TradingStrategy Initialization")
print("-" * 80)

try:
    # Import TradingStrategy but DON'T initialize it (would start trading)
    from trading_strategy import TradingStrategy
    print("✅ TradingStrategy class available")
    print("   ⚠️  Note: Not initializing to avoid starting trading cycle")
except Exception as e:
    print(f"❌ TradingStrategy import failed: {e}")
    import traceback
    traceback.print_exc()

print()
print("📋 STEP 5: Checking Multi-Account Manager")
print("-" * 80)

try:
    from multi_account_broker_manager import MultiAccountBrokerManager
    print("✅ MultiAccountBrokerManager class available")
except Exception as e:
    print(f"❌ MultiAccountBrokerManager import failed: {e}")

print()
print("=" * 80)
print("DIAGNOSIS SUMMARY")
print("=" * 80)

issues_found = []
recommendations = []

# Analyze findings
if not coinbase_key or not coinbase_secret:
    issues_found.append("❌ Coinbase credentials not configured")
    recommendations.append("Set COINBASE_API_KEY and COINBASE_API_SECRET in .env")

if not kraken_master_key or not kraken_master_secret:
    issues_found.append("❌ Kraken MASTER credentials not configured")
    recommendations.append("Set KRAKEN_MASTER_API_KEY and KRAKEN_MASTER_API_SECRET in .env")

if not alpaca_key or not alpaca_secret:
    issues_found.append("❌ Alpaca credentials not configured")
    recommendations.append("Set ALPACA_API_KEY and ALPACA_API_SECRET in .env")

if not alpaca_base_url:
    issues_found.append("⚠️  Alpaca base URL not set")
    recommendations.append("Set ALPACA_BASE_URL=https://paper-api.alpaca.markets in .env")

if issues_found:
    print("\n🔍 ISSUES FOUND:")
    for issue in issues_found:
        print(f"   {issue}")
    
    print("\n💡 RECOMMENDATIONS:")
    for rec in recommendations:
        print(f"   • {rec}")
else:
    print("\n✅ All credentials appear to be configured!")
    print("\nℹ️  If brokers are still not trading, check:")
    print("   1. Verify credentials are valid (not expired, correct format)")
    print("   2. Check broker API permissions (read, write, trade)")
    print("   3. Review bot logs for connection errors: tail -f nija.log")
    print("   4. Ensure minimum balance requirements are met ($2+ for NIJA)")

print()
print("=" * 80)
print("Diagnostic complete. Check the results above for issues.")
print("=" * 80)
