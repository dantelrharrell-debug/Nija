#!/usr/bin/env python3
import os
import sys
from coinbase_advanced_py.rest import CoinbaseClient

# Fetch API keys from environment
API_KEY = os.environ.get("COINBASE_API_KEY")
API_SECRET = os.environ.get("COINBASE_API_SECRET")

# Check if keys exist
if not API_KEY or not API_SECRET:
    print("⚠️ Coinbase API keys not detected. Exiting...")
    sys.exit(1)

# Initialize Coinbase client
client = CoinbaseClient(
    api_key=API_KEY,
    api_secret=API_SECRET,
    sandbox=False  # set True if you want to test in sandbox
)

print("🌟 Starting Nija bot live snapshot...")
print("🔹 Coinbase API keys detected — live trading enabled.\n")

# Fetch account information safely
try:
    accounts = client.get_accounts()
    if not accounts:
        print("⚠️ No accounts found.")
except Exception as e:
    print(f"❌ Error fetching accounts: {e}")
    accounts = []

# Fetch open orders/positions if available
try:
    open_orders = client.get_open_orders() if hasattr(client, 'get_open_orders') else []
except Exception as e:
    print(f"❌ Error fetching open orders: {e}")
    open_orders = []

# Print live snapshot
print("===== NIJA BOT LIVE SNAPSHOT =====")
print(f"Trading Loop: {'✅ Running' if True else '❌ Stopped'}")  # Update with your loop status if needed
print(f"Coinbase API: {'✅ Connected' if accounts else '❌ Error'}")
print(f"Number of Accounts: {len(accounts)}")
print("Open Orders/Positions:")
if open_orders:
    for o in open_orders:
        print(f"  {o}")
else:
    print("  None")
print("=================================\n")
