# test_client.py
from nija_client import CoinbaseClient

client = CoinbaseClient()
accounts = client.get_accounts()
for a in accounts:
    name = a.get("name", "<unknown>")
    bal = a.get("balance", {})
    print(f"{name}: {bal.get('amount','0')} {bal.get('currency','?')}")
