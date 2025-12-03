import os
import time
import hmac
import hashlib
import requests

API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")  # Optional

BASE_URL = "https://api.coinbase.com"

def test_classic_api():
    """Test Classic API Key with passphrase"""
    if not API_PASSPHRASE:
        print("⚠️ Classic API test skipped (no passphrase provided)")
        return

    timestamp = str(int(time.time()))
    method = "GET"
    request_path = "/v2/accounts"
    body = ""
    message = timestamp + method + request_path + body
    signature = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()

    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": signature,
        "CB-ACCESS-TIMESTAMP": timestamp,
        "CB-ACCESS-PASSPHRASE": API_PASSPHRASE,
        "CB-VERSION": "2025-11-05",
    }

    r = requests.get(BASE_URL + request_path, headers=headers)
    print("Classic API response:", r.status_code, r.text[:200])

def test_jwt_api():
    """Test Advanced JWT API Key"""
    headers = {
        "Authorization": f"Bearer {API_SECRET}",  # JWT secret goes here
        "CB-VERSION": "2025-11-05",
    }

    r = requests.get(BASE_URL + "/v2/accounts", headers=headers)
    print("JWT API response:", r.status_code, r.text[:200])

if __name__ == "__main__":
    print("=== Testing Classic API ===")
    test_classic_api()
    print("\n=== Testing JWT API ===")
    test_jwt_api()
