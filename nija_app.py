import os
import sys

def preflight_check():
    required_vars = ["COINBASE_API_KEY", "COINBASE_API_SECRET", "COINBASE_API_PASSPHRASE"]
    missing = [var for var in required_vars if not os.getenv(var)]
    if missing:
        print(f"❌ Missing Coinbase credentials: {', '.join(missing)}")
        sys.exit(1)  # stop the app from starting
    else:
        print("✅ All Coinbase credentials detected.")

# Call this at startup
preflight_check()

import os
import time
import hmac
import hashlib
import requests
from flask import Flask, jsonify

# ----------------------------
# Flask app initialization
# ----------------------------
app = Flask(__name__)

# ----------------------------
# Coinbase API credentials
# ----------------------------
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_BASE = "https://api.coinbase.com"

# ----------------------------
# Helper to generate Coinbase signature
# ----------------------------
def generate_signature(path, method="GET", body=""):
    ts = str(int(time.time()))
    prehash = ts + method.upper() + path + body
    sig = hmac.new(API_SECRET.encode(), prehash.encode(), hashlib.sha256).hexdigest()
    return ts, sig

# ----------------------------
# Preflight API permission check
# ----------------------------
def check_permissions():
    path = "/v2/accounts"
    ts, sig = generate_signature(path)
    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": sig,
        "CB-ACCESS-TIMESTAMP": ts,
        "CB-VERSION": "2025-11-02",
    }
    r = requests.get(API_BASE + path, headers=headers)

    if r.status_code == 401:
        raise RuntimeError("❌ Coinbase API Unauthorized (401). Check your API key and permissions.")
    elif r.status_code == 403:
        raise RuntimeError("❌ Coinbase API Forbidden (403). Key may lack trade permissions.")
    elif r.status_code != 200:
        raise RuntimeError(f"❌ Coinbase API returned {r.status_code}: {r.text}")

    print("✅ Coinbase API preflight passed — keys valid and permissions OK")
    data = r.json()
    for account in data.get("data", []):
        if account.get("currency") == "USD":
            print(f"💰 USD balance: ${account.get('balance', {}).get('amount', 0)}")

# ----------------------------
# Function to get USD balance
# ----------------------------
def get_usd_balance():
    path = "/v2/accounts"
    ts, sig = generate_signature(path)
    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": sig,
        "CB-ACCESS-TIMESTAMP": ts,
        "CB-VERSION": "2025-11-02",
    }
    r = requests.get(API_BASE + path, headers=headers)
    r.raise_for_status()  # Will raise HTTPError for non-200 responses

    data = r.json()
    for account in data.get("data", []):
        if account.get("currency") == "USD":
            return float(account.get("balance", {}).get("amount", 0))
    return 0.0

# ----------------------------
# Run preflight check immediately
# ----------------------------
if not API_KEY or not API_SECRET:
    raise RuntimeError("❌ Coinbase API key or secret is missing.")
check_permissions()

# ----------------------------
# Flask endpoints
# ----------------------------
@app.route("/test-balance")
def test_balance():
    balance = get_usd_balance()
    return jsonify({"USD_Balance": balance})

@app.route("/")
def index():
    return "Nija AI Bot Web Service Running"

# ----------------------------
# Run Flask app
# ----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
