# test_coinbase_keys.py
import os
import time
import hmac
import hashlib
import requests

API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
BASE_URL = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

if not API_KEY or not API_SECRET:
    raise ValueError("COINBASE_API_KEY or COINBASE_API_SECRET not set in environment")

def get_headers(method, path, body=""):
    timestamp = str(int(time.time()))
    message = f"{timestamp}{method}{path}{body}"
    signature = hmac.new(
        API_SECRET.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()

    return {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": signature,
        "CB-ACCESS-TIMESTAMP": timestamp,
        "Content-Type": "application/json"
    }

def test_accounts():
    url = f"{BASE_URL}/v2/accounts"
    headers = get_headers("GET", "/v2/accounts")
    try:
        resp = requests.get(url, headers=headers)
        if resp.status_code == 200:
            print("✅ API keys are valid! Accounts fetched:")
            print(resp.json())
        elif resp.status_code in (401, 403):
            print("❌ Unauthorized! Check API key/secret. Passphrase not needed for Advanced API.")
        else:
            print(f"❌ Unexpected status {resp.status_code}: {resp.text}")
    except Exception as e:
        print(f"❌ Error connecting to Coinbase: {e}")

if __name__ == "__main__":
    test_accounts()
