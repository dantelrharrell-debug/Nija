import os
import time
import hmac
import hashlib
import requests
from flask import Flask, jsonify

app = Flask(__name__)

API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_BASE = "https://api.coinbase.com"

def generate_signature(path, method="GET", body=""):
    ts = str(int(time.time()))
    prehash = ts + method.upper() + path + body
    sig = hmac.new(API_SECRET.encode(), prehash.encode(), hashlib.sha256).hexdigest()
    return ts, sig

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
    if r.status_code != 200:
        print(f"Error fetching balance: {r.status_code} {r.text}")
        return 0.0
    data = r.json()
    for account in data.get("data", []):
        if account.get("currency") == "USD":
            return float(account.get("balance", {}).get("amount", 0))
    return 0.0

@app.route("/test-balance")
def test_balance():
    balance = get_usd_balance()
    return jsonify({"USD_Balance": balance})

@app.route("/")
def index():
    return "Nija AI Bot Web Service Running"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
