#!/usr/bin/env python3
# nija_bot_web.py

import sys, os

# --- Add vendored libraries to Python path ---
ROOT = os.path.dirname(os.path.abspath(__file__))
VENDOR_PATH = os.environ.get("VENDOR_FOLDER_PATH", "vendor")
vendor_abs = os.path.join(ROOT, VENDOR_PATH)
if os.path.isdir(vendor_abs):
    sys.path.insert(0, vendor_abs)

# --- Load .env automatically if present ---
env_path = os.path.join(ROOT, ".env")
if os.path.isfile(env_path):
    for raw in open(env_path):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

# --- Imports ---
from flask import Flask, request, jsonify
import pandas as pd
import numpy as np
import matplotlib
import requests

# --- Initialize Coinbase client (or dummy) ---
try:
    from coinbase_advanced_py.client import CoinbaseClient
    api_key = os.getenv("COINBASE_API_KEY", "YOUR_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET", "YOUR_API_SECRET")
    api_passphrase = os.getenv("COINBASE_API_PASSPHRASE", "YOUR_API_PASSPHRASE")
    client = CoinbaseClient(api_key, api_secret, api_passphrase)
    print("✅ CoinbaseClient initialized")
except ModuleNotFoundError:
    print("⚠️ coinbase_advanced_py not found, using DummyClient for simulation")
    class CoinbaseClient:
        def __init__(self, *args, **kwargs):
            print("Dummy CoinbaseClient initialized")
        def get_accounts(self):
            return [{"currency":"USD","balance":"1000.00"}]
        def place_order(self, **kwargs):
            print("Simulated order:", kwargs)
            return {"status":"simulated", "order": kwargs}
    client = CoinbaseClient()

# --- Flask App ---
app = Flask(__name__)

@app.route("/")
def index():
    return jsonify({"status": "ok", "bot": "Nija AI Trading Bot"}), 200

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    print("Webhook received:", data)
    # Placeholder for trading logic
    return jsonify({"status": "received"}), 200

@app.route("/health")
def health():
    try:
        accounts = client.get_accounts()
    except Exception as e:
        return jsonify({"status":"error","detail": str(e)}), 500
    return jsonify({"status":"ok","accounts_preview": accounts[:2]}), 200

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
