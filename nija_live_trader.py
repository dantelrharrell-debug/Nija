#!/usr/bin/env python3
"""
nija_live_trader.py — Railway-compatible Coinbase live trading
Relies entirely on environment variables (no PEM/JWT files)
"""

import os
import time
import hmac
import hashlib
import base64
import requests
import json
from loguru import logger

# =======================
# Load Environment Variables
# =======================
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")
COINBASE_API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")
COINBASE_API_BASE = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

if not all([COINBASE_API_KEY, COINBASE_API_SECRET, COINBASE_API_PASSPHRASE]):
    logger.error("Coinbase API credentials not found in environment variables.")
    exit(1)

logger.info("Environment variables loaded successfully.")

# =======================
# Coinbase API Client
# =======================
class CoinbaseClient:
    def __init__(self, api_key, api_secret, passphrase, base_url="https://api.coinbase.com"):
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.base_url = base_url.rstrip("/")

    def _get_headers(self, method, path, body=""):
        timestamp = str(int(time.time()))
        message = f"{timestamp}{method.upper()}{path}{body}"
        hmac_key = base64.b64decode(self.api_secret)
        signature = hmac.new(hmac_key, message.encode("utf-8"), hashlib.sha256).digest()
        signature_b64 = base64.b64encode(signature).decode()

        return {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": signature_b64,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "CB-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json"
        }

    def get_accounts(self):
        path = "/accounts"
        url = f"{self.base_url}{path}"
        headers = self._get_headers("GET", path)
        r = requests.get(url, headers=headers)
        r.raise_for_status()
        return r.json()

    def place_order(self, product_id, side, price, size, order_type="limit"):
        path = "/orders"
        body = {
            "product_id": product_id,
            "side": side,
            "price": price,
            "size": size,
            "type": order_type
        }
        body_json = json.dumps(body)
        headers = self._get_headers("POST", path, body_json)
        url = f"{self.base_url}{path}"
        r = requests.post(url, headers=headers, data=body_json)
        r.raise_for_status()
        return r.json()

# =======================
# Live Trading Loop
# =======================
def main():
    client = CoinbaseClient(COINBASE_API_KEY, COINBASE_API_SECRET, COINBASE_API_PASSPHRASE, COINBASE_API_BASE)
    logger.info("Coinbase client initialized.")

    try:
        accounts = client.get_accounts()
        logger.info(f"Accounts fetched: {accounts}")
    except Exception as e:
        logger.error(f"Error fetching accounts: {e}")
        return

    # Example: Place a test order (replace with your strategy)
    try:
        test_order = client.place_order(product_id="BTC-USD", side="buy", price="20000.00", size="0.001")
        logger.info(f"Test order placed: {test_order}")
    except Exception as e:
        logger.error(f"Error placing order: {e}")

if __name__ == "__main__":
    main()
