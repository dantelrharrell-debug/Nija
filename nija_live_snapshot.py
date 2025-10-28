#!/usr/bin/env python3
import os
from nija_client import client, start_trading

print("🌟 Starting Nija bot snapshot...")

# -------------------------------
# Start trading loop
# -------------------------------
trading_thread = start_trading()

# -------------------------------
# Snapshot accounts
# -------------------------------
try:
    accounts = client.get_accounts()
    print("===== NIJA BOT LIVE SNAPSHOT =====")
    print("Trading Loop: ✅ Running")
    print("Coinbase Accounts:")
    for acc in accounts:
        print(f" - {acc['currency']}: {acc['balance']['amount']}")
    print("==================================")
except Exception as e:
    print("===== NIJA BOT LIVE SNAPSHOT =====")
    print("Trading Loop: ❌ Stopped")
    print(f"Coinbase API Error: {e}")
    print("==================================")
