# nija_client.py
import os
from coinbase_advanced.client import Client

COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")
COINBASE_API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")
COINBASE_ACCOUNT_ID = os.getenv("COINBASE_ACCOUNT_ID")

def get_coinbase_client():
    if not all([COINBASE_API_KEY, COINBASE_API_SECRET, COINBASE_API_PASSPHRASE]):
        raise ValueError("Missing COINBASE env vars")
    client = Client(api_key=COINBASE_API_KEY, api_secret=COINBASE_API_SECRET, api_passphrase=COINBASE_API_PASSPHRASE)
    return client
