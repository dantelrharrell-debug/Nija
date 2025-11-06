# nija_coinbase_connect.py
import os
import requests
import hmac
import hashlib
import time
import base64
import json

# Load from environment variables (set these in Render or .env)
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_BASE = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

if not API_KEY or not API_SECRET:
    raise SystemExit("❌ API_KEY or API_SECRET not set in environment!")

def get_accounts():
    """
    Fetch account balances from Coinbase Advanced API using Key + Secret
    """
    path = "/v2/accounts"
    url = API_BASE + path
    timestamp = str(int(time.time()))
    message = timestamp + "GET" + path
    signature = hmac.new(
        API_SECRET.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()

    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": signature,
        "CB-ACCESS-TIMESTAMP": timestamp,
        "CB-VERSION": "2025-11-06"
    }

    response = requests.get(url, headers=headers)
    try:
        data = response.json()
    except json.JSONDecodeError:
        data = {"error": "Invalid response", "raw": response.text}

    return data

if __name__ == "__main__":
    accounts = get_accounts()
    print(json.dumps(accounts, indent=4))
