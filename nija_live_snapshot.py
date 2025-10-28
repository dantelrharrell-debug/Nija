import os
from coinbase_advanced_py.client import CoinbaseClient

# --- Initialize Coinbase client ---
client = CoinbaseClient(
    api_key=os.environ.get("COINBASE_API_KEY"),
    api_secret=os.environ.get("COINBASE_API_SECRET"),
    sandbox=False  # False = live trading
)

print("\n===== NIJA BOT LIVE SNAPSHOT =====")

# --- Trading loop status placeholder ---
# Replace this with your actual trading loop check if needed
trading_loop_running = False
print(f"Trading Loop: {'✅ Running' if trading_loop_running else '❌ Stopped'}")

# --- Connect to Coinbase and fetch accounts ---
try:
    accounts = client.accounts.list()  # updated method for v1.8.2
    if accounts:
        print("Coinbase API: ✅ Connected")
        print(f"Number of Accounts: {len(accounts)}")
        print("Open Orders/Positions:")
        for account in accounts:
            print(f" - {account['balance']['currency']}: {account['balance']['amount']}")
    else:
        print("Coinbase API: ❌ No accounts found")
except Exception as e:
    print(f"Coinbase API: ❌ Error connecting: {e}")

print("=================================")
