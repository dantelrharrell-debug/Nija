import os
import time
import hmac
import hashlib
import requests
from flask import Flask, jsonify

app = Flask(__name__)

# --- Coinbase Advanced API keys ---
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_BASE = "https://api.coinbase.com"

# --- Helper to generate Coinbase signature ---
def generate_signature(path, method="GET", body=""):
    ts = str(int(time.time()))
    prehash = ts + method.upper() + path + body
    sig = hmac.new(API_SECRET.encode(), prehash.encode(), hashlib.sha256).hexdigest()
    return ts, sig

# --- Check API permissions ---
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
