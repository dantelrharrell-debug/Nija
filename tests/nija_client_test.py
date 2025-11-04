# nija_client_test.py
import os
from coinbase_advanced_py import Client

c = Client(
    api_key=os.getenv("COINBASE_API_KEY"),
    api_secret=os.getenv("COINBASE_API_SECRET"),
    api_passphrase=os.getenv("COINBASE_API_PASSPHRASE")
)

try:
    accounts = c.get_accounts()
    print("OK — accounts:", len(accounts))
    print(accounts[:1])
except Exception as e:
    print("coinbase error:", e)
