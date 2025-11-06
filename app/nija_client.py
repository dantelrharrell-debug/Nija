# nija_client.py
import os
import time
import hmac
import hashlib
import base64
import requests
import logging

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("nija_client")

# Environment variables
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")
BASE_URL = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

HEADERS = {
    "CB-ACCESS-KEY": API_KEY,
    "CB-ACCESS-PASSPHRASE": API_PASSPHRASE,
    "Content-Type": "application/json"
}

def safe_get(endpoint):
    url = f"{BASE_URL}{endpoint}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        log.error(f"GET {endpoint} failed: {e}")
        return {"error": str(e)}

def safe_post(endpoint, data):
    url = f"{BASE_URL}{endpoint}"
    try:
        response = requests.post(url, headers=HEADERS, json=data, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        log.error(f"POST {endpoint} failed: {e}")
        return {"error": str(e)}

def get_account_balance(currency="USD"):
    data = safe_get("/v2/accounts")
    if "error" in data:
        return 0
    for acc in data.get("data", []):
        if acc["currency"] == currency:
            return float(acc["balance"]["amount"])
    return 0

def calculate_position_size(balance, percent=5):
    """
    balance: float, current account balance
    percent: int, % of balance to use
    """
    percent = max(2, min(percent, 10))  # clamp 2–10%
    return balance * (percent / 100)

def place_order(symbol, side, size, price=None):
    """
    side: 'buy' or 'sell'
    size: float, in units of crypto
    price: float or None for market
    """
    data = {
        "type": "market" if price is None else "limit",
        "side": side,
        "product_id": symbol,
        "size": str(size)
    }
    if price:
        data["price"] = str(price)
    return safe_post(f"/v2/orders", data)
