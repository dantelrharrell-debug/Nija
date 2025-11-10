# test_client.py
from nija_client import CoinbaseClient

try:
    client = CoinbaseClient()
    account_info = client.get_account()
    print("✅ Connected to Coinbase! Account info:")
    for acct in account_info.get("data", []):
        print(f"- {acct['name']} | Balance: {acct['balance']['amount']} {acct['balance']['currency']}")
except Exception as e:
    print("❌ Connection failed:", e)
