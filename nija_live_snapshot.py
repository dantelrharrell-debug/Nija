# nija_live_snapshot.py
from coinbase_advanced_py.client import CoinbaseClient

import os
import sys

API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")

if not API_KEY or not API_SECRET:
    print("❌ Coinbase API keys not set in environment.")
    sys.exit(1)

try:
    client = CoinbaseClient(api_key=API_KEY, api_secret=API_SECRET)
    accounts = client.get_accounts()
except AttributeError:
    print("❌ CoinbaseClient object missing 'get_accounts'. Check library version!")
    sys.exit(1)
except Exception as e:
    print(f"❌ Coinbase API error: {e}")
    sys.exit(1)

print("===== NIJA BOT LIVE SNAPSHOT =====")
print(f"Number of Accounts: {len(accounts)}")
for acc in accounts:
    print(f" - {acc['currency']}: {acc['balance']}")
print("=================================")
