# nija_client.py
import os
import time
import hmac
import hashlib
import base64
import requests
import json

# Load environment variables
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")
BASE_URL = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

if not all([API_KEY, API_SECRET, API_PASSPHRASE]):
    raise EnvironmentError("Missing Coinbase API credentials in environment variables")

def cdp_get():
    """
    Fetch account info from Coinbase Advanced API (CDP endpoint)
    Returns a dict with account data.
    """
    timestamp = str(int(time.time()))
    method = "GET"
    request_path = "/v2/accounts"  # Adjust endpoint if needed
    body = ""

    # Create the signature
    message = timestamp + method + request_path + body
    hmac_key = base64.b64decode(API_SECRET)
    signature = hmac.new(hmac_key, message.encode(), hashlib.sha256).digest()
    signature_b64 = base64.b64encode(signature).decode()

    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": signature_b64,
        "CB-ACCESS-TIMESTAMP": timestamp,
        "CB-ACCESS-PASSPHRASE": API_PASSPHRASE,
        "Content-Type": "application/json"
    }

    try:
        response = requests.get(BASE_URL + request_path, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        return {"status": "error", "message": str(e)}
