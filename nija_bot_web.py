#!/usr/bin/env python3
# nija_bot_web.py

# --- Add vendored libraries to Python path ---
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "vendor"))

# --- Imports ---
from coinbase_advanced_py.client import CoinbaseClient
from flask import Flask, request, jsonify
import pandas as pd
import numpy as np
import matplotlib
import requests
import os

app = Flask(__name__)

# --- Initialize Coinbase client ---
api_key = os.getenv("API_KEY", "YOUR_API_KEY")
api_secret = os.getenv("API_SECRET", "YOUR_API_SECRET")
api_passphrase = os.getenv("API_PASSPHRASE", "YOUR_API_PASSPHRASE")
client = CoinbaseClient(api_key, api_secret, api_passphrase)

# --- Root route ---
@app.route("/")
def index():
    return jsonify({"status": "ok", "bot": "Nija AI Trading Bot"}), 200

# --- Example webhook route ---
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    print("Webhook received:", data)
    # Add trading logic here
    return jsonify({"status": "received"}), 200

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
