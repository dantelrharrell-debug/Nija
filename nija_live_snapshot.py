import os
from coinbase_advanced_py import CoinbaseClient  # <-- updated path

# Initialize client
client = CoinbaseClient(
    api_key=os.environ.get("COINBASE_API_KEY"),
    api_secret=os.environ.get("COINBASE_API_SECRET"),
    sandbox=False
)

print("\n===== NIJA BOT LIVE SNAPSHOT =====")

trading_loop_running = False
print(f"Trading Loop: {'✅ Running' if trading_loop_running else '❌ Stopped'}")

# Fetch accounts
try:
    accounts = client.accounts.list()  # v1.8.2 method
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
