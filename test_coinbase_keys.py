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
API_BASE = os.getenv("COINBASE_API_BASE", "https://api.pro.coinbase.com")  # Pro API

if not all([API_KEY, API_SECRET, API_PASSPHRASE]):
    raise SystemExit("❌ Missing one or more Coinbase credentials.")

# Create Coinbase Pro / Advanced signature
def make_headers(method, path, body=""):
    timestamp = str(int(time.time()))
    message = timestamp + method.upper() + path + body
    hmac_key = base64.b64decode(API_SECRET)
    signature = hmac.new(hmac_key, message.encode(), hashlib.sha256)
    signature_b64 = base64.b64encode(signature.digest()).decode()

    return {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": signature_b64,
        "CB-ACCESS-TIMESTAMP": timestamp,
        "CB-ACCESS-PASSPHRASE": API_PASSPHRASE,
        "Content-Type": "application/json"
    }

# Test: get accounts
try:
    r = requests.get(f"{API_BASE}/accounts", headers=make_headers("GET", "/accounts"))
    if r.status_code == 200:
        print("✅ Coinbase API credentials are valid! Here are your accounts:")
        print(json.dumps(r.json(), indent=2))
    elif r.status_code == 401:
        print("❌ Unauthorized! Check your API key, secret, passphrase, and permissions.")
    else:
        print(f"❌ Unexpected response: {r.status_code} {r.text}")
except Exception as e:
    print(f"❌ Error connecting to Coinbase API: {e}")
