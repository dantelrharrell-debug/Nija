# test_coinbase.py
import os
from coinbase.wallet.client import Client

# Prefer reading secrets from environment variables
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")

# If your secret was stored with literal "\n" sequences (common when copying),
# convert them back to real newlines:
if API_SECRET and "\\n" in API_SECRET:
    API_SECRET = API_SECRET.replace("\\n", "\n")

if not API_KEY or not API_SECRET:
    raise SystemExit("Missing COINBASE_API_KEY or COINBASE_API_SECRET environment variables.")

client = Client(API_KEY, API_SECRET)

try:
    accounts = client.get_accounts()  # fetch accounts
    for acc in accounts['data']:
        name = acc.get('name') or acc.get('currency')
        balance = acc.get('balance', {}).get('amount')
        currency = acc.get('balance', {}).get('currency')
        print(f"{name}: {balance} {currency}")
except Exception as e:
    print("Error connecting to Coinbase:", type(e).__name__, e)
