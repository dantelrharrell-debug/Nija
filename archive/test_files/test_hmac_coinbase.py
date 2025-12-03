# test_coinbase_hmac.py
import os
import requests
import hmac
import hashlib
import time

API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE", "")
BASE_URL = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

def test_hmac_accounts():
    if not API_KEY or not API_SECRET:
        print("❌ Missing COINBASE_API_KEY or COINBASE_API_SECRET")
        return

    timestamp = str(int(time.time()))
    method = "GET"
    request_path = "/v2/accounts"   # standard Coinbase accounts path
    body = ""

    message = timestamp + method + request_path + body
    signature = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()

    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": signature,
        "CB-ACCESS-TIMESTAMP": timestamp,
        "CB-VERSION": "2025-11-11",
    }
    if API_PASSPHRASE:
        headers["CB-ACCESS-PASSPHRASE"] = API_PASSPHRASE

    try:
        r = requests.get(BASE_URL + request_path, headers=headers, timeout=10)
        print("Status Code:", r.status_code)
        print("Response:", r.text)
    except Exception as e:
        print("Exception:", e)

if __name__ == "__main__":
    test_hmac_accounts()
