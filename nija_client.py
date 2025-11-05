import os
import time
import hmac
import hashlib
import base64
import requests
import json

API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")  # optional
BASE_URL = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

def get_coinbase_headers(method, path, body=""):
    """
    Build headers for Coinbase REST request, using optional passphrase.
    """
    ts = str(int(time.time()))
    message = ts + method.upper() + path + body

    # Create HMAC signature
    signature = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()

    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": signature,
        "CB-ACCESS-TIMESTAMP": ts,
        "Content-Type": "application/json",
    }

    # Only add passphrase if present
    if API_PASSPHRASE:
        headers["CB-ACCESS-PASSPHRASE"] = API_PASSPHRASE

    return headers

def manual_get_accounts():
    path = "/api/v3/brokerage/accounts"
    url = BASE_URL + path

    headers = get_coinbase_headers("GET", path)
    response = requests.get(url, headers=headers, timeout=10)

    if response.status_code == 200:
        return response.json()
    elif response.status_code == 401:
        raise RuntimeError("❌ Unauthorized: Check API key/secret and permissions (wallet/accounts).")
    else:
        raise RuntimeError(f"❌ Failed to fetch accounts: {response.status_code} {response.text}")

def get_all_accounts():
    """
    Main entry point to fetch all Coinbase accounts.
    """
    try:
        return manual_get_accounts()
    except Exception as e:
        print(f"⚠️ manual_get_accounts failed: {e}")
        raise
