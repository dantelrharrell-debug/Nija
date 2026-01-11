#!/usr/bin/env python3
"""
NIJA Trading Status Verification Script
=======================================

Verifies if NIJA is connected and trading for master and user accounts.

Date: January 11, 2026
"""

import os
import sys

# Try to load .env file
try:
    from dotenv import load_dotenv
    load_dotenv('.env')
    print("✅ Loaded environment variables from .env")
except ImportError:
    print("⚠️  python-dotenv not installed, using system environment variables")
except Exception as e:
    print(f"⚠️  Could not load .env: {e}")

print()
print("=" * 70)
print("🔍 NIJA TRADING STATUS VERIFICATION")
print("=" * 70)
print()

# Check environment configuration
print("📋 ENVIRONMENT CONFIGURATION:")
print()

multi_broker = os.getenv("MULTI_BROKER_INDEPENDENT", "")
if multi_broker.lower() in ["true", "1", "yes"]:
    print("   ✅ MULTI_BROKER_INDEPENDENT: ENABLED")
    multi_broker_enabled = True
elif multi_broker:
    print(f"   ⚠️  MULTI_BROKER_INDEPENDENT: {multi_broker} (not recognized as enabled)")
    multi_broker_enabled = False
else:
    print("   ⚠️  MULTI_BROKER_INDEPENDENT: NOT SET (defaults to 'true' in code)")
    multi_broker_enabled = True  # Code defaults to true

paper_mode = os.getenv("PAPER_MODE", "")
if paper_mode.lower() in ["false", "0", "no"]:
    print("   ✅ PAPER_MODE: DISABLED (Live Trading)")
elif paper_mode.lower() in ["true", "1", "yes"]:
    print("   ⚠️  PAPER_MODE: ENABLED (Simulated Trading)")
else:
    print("   ✅ PAPER_MODE: NOT SET (Live Trading)")

print()

# Check Master Account Credentials
print("🔷 MASTER ACCOUNT CREDENTIALS:")
print()

master_brokers = []

# Coinbase
coinbase_key = os.getenv("COINBASE_API_KEY", "")
coinbase_secret = os.getenv("COINBASE_API_SECRET", "")
if coinbase_key and coinbase_secret:
    print(f"   ✅ Coinbase: CONFIGURED")
    print(f"      - API Key: {len(coinbase_key)} chars")
    print(f"      - API Secret: {len(coinbase_secret)} chars")
    master_brokers.append("coinbase")
else:
    print(f"   ❌ Coinbase: NOT CONFIGURED")
    if not coinbase_key:
        print(f"      - Missing: COINBASE_API_KEY")
    if not coinbase_secret:
        print(f"      - Missing: COINBASE_API_SECRET")

# Kraken Master
kraken_master_key = os.getenv("KRAKEN_MASTER_API_KEY", "")
kraken_master_secret = os.getenv("KRAKEN_MASTER_API_SECRET", "")
if kraken_master_key and kraken_master_secret:
    print(f"   ✅ Kraken Master: CONFIGURED")
    print(f"      - API Key: {len(kraken_master_key)} chars")
    print(f"      - API Secret: {len(kraken_master_secret)} chars")
    master_brokers.append("kraken_master")
else:
    print(f"   ❌ Kraken Master: NOT CONFIGURED")
    if not kraken_master_key:
        print(f"      - Missing: KRAKEN_MASTER_API_KEY")
    if not kraken_master_secret:
        print(f"      - Missing: KRAKEN_MASTER_API_SECRET")

# Alpaca
alpaca_key = os.getenv("ALPACA_API_KEY", "")
alpaca_secret = os.getenv("ALPACA_API_SECRET", "")
alpaca_paper = os.getenv("ALPACA_PAPER", "false")
if alpaca_key and alpaca_secret:
    mode = "Paper Trading" if alpaca_paper.lower() in ["true", "1", "yes"] else "Live Trading"
    print(f"   ✅ Alpaca: CONFIGURED ({mode})")
    print(f"      - API Key: {len(alpaca_key)} chars")
    print(f"      - API Secret: {len(alpaca_secret)} chars")
    master_brokers.append("alpaca")
else:
    print(f"   ⚠️  Alpaca: NOT CONFIGURED (Optional)")

# OKX
okx_key = os.getenv("OKX_API_KEY", "")
okx_secret = os.getenv("OKX_API_SECRET", "")
okx_passphrase = os.getenv("OKX_PASSPHRASE", "")
if okx_key and okx_secret and okx_passphrase and "REQUIRED" not in okx_passphrase:
    print(f"   ✅ OKX: CONFIGURED")
    print(f"      - API Key: {len(okx_key)} chars")
    print(f"      - API Secret: {len(okx_secret)} chars")
    master_brokers.append("okx")
else:
    print(f"   ⚠️  OKX: NOT CONFIGURED (Optional)")

print()

# Check User Account Credentials
print("👥 USER ACCOUNT CREDENTIALS:")
print()

user_brokers = []

# User: Daivon Frazier (Kraken)
kraken_user_daivon_key = os.getenv("KRAKEN_USER_DAIVON_API_KEY", "")
kraken_user_daivon_secret = os.getenv("KRAKEN_USER_DAIVON_API_SECRET", "")
if kraken_user_daivon_key and kraken_user_daivon_secret:
    print(f"   ✅ User: Daivon Frazier (Kraken): CONFIGURED")
    print(f"      - API Key: {len(kraken_user_daivon_key)} chars")
    print(f"      - API Secret: {len(kraken_user_daivon_secret)} chars")
    user_brokers.append("kraken_user_daivon")
else:
    print(f"   ⚠️  User: Daivon Frazier (Kraken): NOT CONFIGURED")

print()

# Summary
print("=" * 70)
print("📊 VERIFICATION SUMMARY:")
print("=" * 70)
print()

print(f"Master Brokers Configured: {len(master_brokers)}")
if master_brokers:
    for broker in master_brokers:
        print(f"   ✅ {broker}")
else:
    print("   ❌ None")

print()

print(f"User Brokers Configured: {len(user_brokers)}")
if user_brokers:
    for broker in user_brokers:
        print(f"   ✅ {broker}")
else:
    print("   ⚠️  None")

print()

# Overall Status
total_brokers = len(master_brokers) + len(user_brokers)

if total_brokers > 0:
    print("🎯 OVERALL STATUS: ✅ CONFIGURED FOR TRADING")
    print()
    print(f"   - Multi-account mode: {'ENABLED' if multi_broker_enabled else 'DISABLED'}")
    print(f"   - Master brokers: {len(master_brokers)}")
    print(f"   - User brokers: {len(user_brokers)}")
    print(f"   - Total brokers: {total_brokers}")
    print()
    
    if multi_broker_enabled:
        print("   ✅ Each broker will trade independently in isolated threads")
        print("   ✅ Failures in one broker won't affect others")
        print("   ✅ Staggered starts prevent API rate limiting")
    else:
        print("   ⚠️  Multi-broker mode is DISABLED")
        print("   ⚠️  Only one broker will trade at a time")
    
    print()
    print("📝 NEXT STEPS:")
    print()
    print("   To verify the bot is ACTIVELY RUNNING:")
    print()
    print("   1. Check process status:")
    print("      ps aux | grep '[b]ot.py'")
    print()
    print("   2. Check recent logs:")
    print("      tail -f nija.log")
    print()
    print("   3. Look for these log patterns:")
    print("      🌐 MULTI-ACCOUNT TRADING MODE ACTIVATED")
    print("      ✅ X INDEPENDENT TRADING THREADS RUNNING")
    print("      🔄 [broker] - Cycle #X")
    print()
    print("   4. Check deployment platform:")
    print("      Railway: railway logs --tail")
    print("      Render: Check dashboard logs")
    print()
    
else:
    print("🎯 OVERALL STATUS: ❌ NOT CONFIGURED")
    print()
    print("   No broker credentials found!")
    print()
    print("   To configure NIJA:")
    print()
    print("   1. Edit .env file and add credentials:")
    print("      - COINBASE_API_KEY and COINBASE_API_SECRET")
    print("      - KRAKEN_MASTER_API_KEY and KRAKEN_MASTER_API_SECRET")
    print("      - ALPACA_API_KEY and ALPACA_API_SECRET (optional)")
    print()
    print("   2. For user accounts:")
    print("      - KRAKEN_USER_DAIVON_API_KEY and KRAKEN_USER_DAIVON_API_SECRET")
    print()
    print("   3. Enable multi-broker mode:")
    print("      - MULTI_BROKER_INDEPENDENT=true")
    print()

print("=" * 70)
print()

# Exit with status code
sys.exit(0 if total_brokers > 0 else 1)
