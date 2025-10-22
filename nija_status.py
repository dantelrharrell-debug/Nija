import sys, os
import threading
from coinbase_advanced_py.client import CoinbaseClient

# -------------------------
# CONFIG - Replace with your keys
# -------------------------
API_KEY = "YOUR_API_KEY_HERE"
API_SECRET = "YOUR_API_SECRET_HERE"

# -------------------------
# 1. Check Coinbase connectivity
# -------------------------
try:
    client = CoinbaseClient(API_KEY, API_SECRET)
    accounts = client.get_accounts()
    if accounts:
        coinbase_status = "✅ Connected"
        account_count = len(accounts)
    else:
        coinbase_status = "⚠️ Connected but no accounts returned"
        account_count = 0
except Exception as e:
    coinbase_status = f"❌ Error: {e}"
    account_count = 0

# -------------------------
# 2. Check trading loop
# -------------------------
# Replace this with your bot's actual thread variable if different
try:
    from debug_client_full import running  # your trading loop flag
    trading_status = "✅ Live" if running else "❌ Stopped"
except Exception:
    trading_status = "⚠️ Could not detect trading loop"

# -------------------------
# 3. Check open positions
# -------------------------
try:
    open_orders = client.get_open_orders() if account_count > 0 else []
    open_positions_count = len(open_orders)
except Exception:
    open_positions_count = 0

# -------------------------
# 4. Print status
# -------------------------
print("\n===== NIJA BOT STATUS =====")
print(f"Trading Loop: {trading_status}")
print(f"Coinbase API: {coinbase_status}")
print(f"Number of Accounts: {account_count}")
print(f"Open Orders/Positions: {open_positions_count}")
print("===========================\n")
