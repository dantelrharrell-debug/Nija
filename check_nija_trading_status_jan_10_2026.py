#!/usr/bin/env python3
"""
NIJA Trading Status Check - January 10, 2026

This script checks if NIJA is trading for master and all user accounts.
Answers the question: "Is NIJA trading for master and all users now?"
"""

import os
import sys
from datetime import datetime

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        load_dotenv(env_path)
        print(f"✅ Loaded environment from {env_path}")
    else:
        print(f"⚠️  .env file not found at {env_path}")
except ImportError:
    print("⚠️  python-dotenv not installed, attempting to read .env manually")
    # Try to load .env manually
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key] = value
        print(f"✅ Manually loaded environment from {env_path}")

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

print("=" * 80)
print("🎯 NIJA TRADING STATUS CHECK")
print("=" * 80)
print(f"📅 Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 80)
print()

# Check environment variables for API keys
print("📊 CHECKING API CREDENTIALS CONFIGURATION")
print("-" * 80)

master_brokers = []
user_brokers = []

# Check Master brokers
if os.getenv("COINBASE_API_KEY") and os.getenv("COINBASE_API_SECRET"):
    master_brokers.append("Coinbase")
    print("✅ Coinbase MASTER - API credentials configured")
else:
    print("❌ Coinbase MASTER - API credentials NOT configured")

if os.getenv("KRAKEN_MASTER_API_KEY") and os.getenv("KRAKEN_MASTER_API_SECRET"):
    master_brokers.append("Kraken")
    print("✅ Kraken MASTER - API credentials configured")
else:
    print("❌ Kraken MASTER - API credentials NOT configured")

if os.getenv("ALPACA_API_KEY") and os.getenv("ALPACA_API_SECRET"):
    master_brokers.append("Alpaca")
    print("✅ Alpaca MASTER - API credentials configured (Paper Trading)")
else:
    print("❌ Alpaca MASTER - API credentials NOT configured")

if os.getenv("OKX_API_KEY") and os.getenv("OKX_API_SECRET"):
    master_brokers.append("OKX")
    print("✅ OKX MASTER - API credentials configured")
else:
    print("❌ OKX MASTER - API credentials NOT configured")

if os.getenv("BINANCE_API_KEY") and os.getenv("BINANCE_API_SECRET"):
    master_brokers.append("Binance")
    print("✅ Binance MASTER - API credentials configured")
else:
    print("❌ Binance MASTER - API credentials NOT configured")

print()

# Check User brokers
if os.getenv("KRAKEN_USER_DAIVON_API_KEY") and os.getenv("KRAKEN_USER_DAIVON_API_SECRET"):
    user_brokers.append("Daivon Frazier (Kraken)")
    print("✅ User #1 (Daivon Frazier) Kraken - API credentials configured")
else:
    print("❌ User #1 (Daivon Frazier) Kraken - API credentials NOT configured")

print()
print("=" * 80)
print("📈 TRADING STATUS SUMMARY")
print("=" * 80)
print()

# Master accounts summary
print("🔷 MASTER ACCOUNTS:")
if master_brokers:
    for broker in master_brokers:
        print(f"   ✅ {broker}")
    print(f"\n   Total: {len(master_brokers)} master brokers configured")
else:
    print("   ❌ No master brokers configured")

print()

# User accounts summary  
print("👤 USER ACCOUNTS:")
if user_brokers:
    for user in user_brokers:
        print(f"   ✅ {user}")
    print(f"\n   Total: {len(user_brokers)} user brokers configured")
else:
    print("   ❌ No user brokers configured")

print()
print("=" * 80)
print("🤖 BOT STATUS")
print("=" * 80)
print()

# Check if bot is configured to run independent multi-broker mode
multi_broker = os.getenv("MULTI_BROKER_INDEPENDENT", "true").lower() in ["true", "1", "yes"]
if multi_broker:
    print("✅ Multi-broker independent trading: ENABLED")
    print("   Each broker will trade independently in isolated threads")
else:
    print("⚠️  Multi-broker independent trading: DISABLED")
    print("   Only single broker will trade")

print()

# Check log file for recent activity
log_file = os.path.join(os.path.dirname(__file__), 'nija.log')
if os.path.exists(log_file):
    print("📋 RECENT LOG ACTIVITY:")
    print("-" * 80)
    try:
        with open(log_file, 'r') as f:
            lines = f.readlines()
            # Get last 20 lines
            recent_lines = lines[-20:] if len(lines) > 20 else lines
            for line in recent_lines:
                # Only show important status lines
                if any(keyword in line for keyword in [
                    'MASTER', 'USER', 'connected', 'TRADING', 'Cycle', 
                    'balance', 'Starting', 'THREADS RUNNING'
                ]):
                    print(line.rstrip())
    except Exception as e:
        print(f"   ⚠️  Could not read log file: {e}")
else:
    print("⚠️  Log file not found - bot may not have run yet")

print()
print("=" * 80)
print("🎯 FINAL ANSWER")
print("=" * 80)
print()

if master_brokers or user_brokers:
    total_accounts = len(master_brokers) + len(user_brokers)
    print(f"✅ NIJA IS CONFIGURED to trade for {total_accounts} account(s):")
    print()
    if master_brokers:
        print(f"   🔷 {len(master_brokers)} MASTER account(s):")
        for broker in master_brokers:
            print(f"      • {broker}")
    if user_brokers:
        print()
        print(f"   👤 {len(user_brokers)} USER account(s):")
        for user in user_brokers:
            print(f"      • {user}")
    print()
    print("📌 NOTE: Configuration is complete. Trading activity depends on:")
    print("   1. Bot is currently running")
    print("   2. Brokers have connected successfully")
    print("   3. Markets have tradeable signals (RSI oversold conditions)")
    print("   4. Adequate balance in each broker account")
    print()
    print("💡 To verify NIJA is actively running:")
    print("   1. Check logs: tail -f nija.log")
    print("   2. Look for 'THREADS RUNNING' message")
    print("   3. Watch for 'Cycle #N' messages every 2.5 minutes")
    print()
else:
    print("❌ NIJA IS NOT CONFIGURED - No broker API credentials found")
    print()
    print("📌 ACTION REQUIRED: Configure API credentials in .env file")
    print()

print("=" * 80)
print("Report complete")
print("=" * 80)
