# nija_client.py
import os
import time
import jwt
import requests
import json
from loguru import logger

# --------------------------
# ENVIRONMENT VARIABLES
# --------------------------
CLIENT_ID = os.getenv("COINBASE_CLIENT_ID")
PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")  # The private key for JWT
API_VERSION = os.getenv("COINBASE_API_VERSION", "2025-11-05")  # today’s CDP version
BASE_URL = os.getenv("COINBASE_API_BASE", "https://api.cdp.coinbase.com")  # CDP endpoint

if not all([CLIENT_ID, PEM_CONTENT]):
    logger.error("Missing Coinbase CDP credentials")
    raise SystemExit(1)

# --------------------------
# JWT GENERATION
# --------------------------
def generate_jwt():
    iat = int(time.time())
    payload = {
        "iss": CLIENT_ID,
        "iat": iat,
        "exp": iat + 300  # Token valid for 5 minutes
    }
    token = jwt.encode(payload, PEM_CONTENT.encode(), algorithm="RS256")
    return token

# --------------------------
# HEADER BUILDER
# --------------------------
def get_headers():
    jwt_token = generate_jwt()
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "CB-VERSION": API_VERSION,
        "Content-Type": "application/json"
    }
    return headers

# --------------------------
# SIMPLE API REQUEST WRAPPER
# --------------------------
def cdp_request(method, path, data=None):
    url = f"{BASE_URL}{path}"
    headers = get_headers()
    try:
        if method.upper() == "GET":
            resp = requests.get(url, headers=headers)
        elif method.upper() == "POST":
            resp = requests.post(url, headers=headers, json=data)
        else:
            raise ValueError("Unsupported method")
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTPError: {e} | Response: {resp.text}")
        return None
    except Exception as e:
        logger.error(f"Request failed: {e}")
        return None

# --------------------------
# EXAMPLE FUNCTIONS
# --------------------------
def get_wallets():
    return cdp_request("GET", "/platform/v1/wallets")

def place_order(wallet_id, product_id, side, size, price=None, order_type="market"):
    data = {
        "wallet_id": wallet_id,
        "product_id": product_id,
        "side": side,
        "size": str(size),
        "type": order_type
    }
    if price:
        data["price"] = str(price)
    return cdp_request("POST", "/platform/v2/orders", data)

# --------------------------
# BASIC LIVE TRADING LOOP (Skeleton)
# --------------------------
def trading_loop():
    logger.info("Starting Nija trading loop...")
    wallets = get_wallets()
    if not wallets:
        logger.error("Failed to fetch wallets, stopping bot")
        return

    # Example: pick first wallet
    wallet_id = wallets[0]["id"]
    logger.info(f"Using wallet: {wallet_id}")

    # Replace with your TradingView/TA signals
    signals = ["buy", "sell", "hold"]
    for signal in signals:
        if signal == "buy":
            result = place_order(wallet_id, "BTC-USD", "buy", 0.01)
            logger.info(f"Buy order result: {result}")
        elif signal == "sell":
            result = place_order(wallet_id, "BTC-USD", "sell", 0.01)
            logger.info(f"Sell order result: {result}")
        time.sleep(1)  # Avoid spamming

if __name__ == "__main__":
    trading_loop()
