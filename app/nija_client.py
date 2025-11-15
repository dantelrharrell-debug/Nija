# app/nija_client.py

import os
import time
import jwt
import requests
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# --- Setup logger ---
logger.remove()
logger.add(lambda m: print(m, end=""), level=os.environ.get("LOG_LEVEL", "INFO"))

# --- Load Coinbase PEM ---
if "COINBASE_PEM_PATH" in os.environ:
    with open(os.environ["COINBASE_PEM_PATH"], "rb") as pem_file:
        pem_data = pem_file.read()
        private_key = serialization.load_pem_private_key(
            pem_data,
            password=None,
            backend=default_backend()
        )
elif "COINBASE_PEM_CONTENT" in os.environ:
    pem_data = os.environ["COINBASE_PEM_CONTENT"].encode()
    private_key = serialization.load_pem_private_key(
        pem_data,
        password=None,
        backend=default_backend()
    )
else:
    logger.error("No Coinbase PEM found!")
    raise Exception("PEM missing")

# --- Coinbase Config ---
COINBASE_ORG_ID = os.environ["COINBASE_ORG_ID"]
COINBASE_API_KEY = os.environ["COINBASE_API_KEY"]
LIVE_TRADING = int(os.environ.get("LIVE_TRADING", 0))
MIN_TRADE_PERCENT = float(os.environ.get("MIN_TRADE_PERCENT", 2)) / 100
MAX_TRADE_PERCENT = float(os.environ.get("MAX_TRADE_PERCENT", 10)) / 100

# --- JWT Generation ---
def generate_jwt():
    current_time = int(time.time())
    payload = {
        "sub": COINBASE_ORG_ID,
        "iat": current_time,
        "exp": current_time + 300  # 5 minutes
    }
    token = jwt.encode(payload, private_key, algorithm="ES256", headers={"kid": COINBASE_API_KEY})
    return token

# --- Coinbase API Call Helper ---
def coinbase_request(method, endpoint, data=None):
    url = f"https://api.coinbase.com{endpoint}"
    headers = {
        "Authorization": f"Bearer {generate_jwt()}",
        "CB-VERSION": "2025-11-14"
    }
    resp = requests.request(method, url, headers=headers, json=data)
    if resp.status_code != 200:
        logger.error(f"Coinbase {method} {endpoint} failed: {resp.status_code} {resp.text}")
    return resp.json() if resp.ok else None

# --- Get Accounts ---
def get_accounts():
    return coinbase_request("GET", "/v2/accounts")

# --- Place Order ---
def place_order(account_id, side, size, product_id):
    if not LIVE_TRADING:
        logger.info(f"[DRY RUN] {side} order for {size} {product_id}")
        return {"status": "dry_run", "size": size}
    data = {
        "type": "market",
        "side": side,
        "product_id": product_id,
        "size": size,
        "funds": None
    }
    endpoint = f"/v2/accounts/{account_id}/orders"
    return coinbase_request("POST", endpoint, data)

# --- Dynamic Trade Sizing ---
def calculate_trade_size(account_balance, risk_percent=None):
    trade_percent = MAX_TRADE_PERCENT if not risk_percent else max(MIN_TRADE_PERCENT, min(MAX_TRADE_PERCENT, risk_percent))
    return round(account_balance * trade_percent, 8)

def place_dynamic_order(account_id, side, product_id, balance=None, risk_percent=None):
    if balance is None:
        accounts = get_accounts()
        if accounts and "data" in accounts:
            for acc in accounts["data"]:
                if acc["id"] == account_id:
                    balance = float(acc["balance"]["amount"])
                    break
        if balance is None:
            logger.error(f"Could not retrieve balance for account {account_id}")
            return None
    trade_size = calculate_trade_size(balance, risk_percent)
    logger.info(f"Placing {side} order of size {trade_size} on {product_id}")
    return place_order(account_id, side, str(trade_size), product_id)

# --- Example usage ---
if __name__ == "__main__":
    accounts = get_accounts()
    if accounts and len(accounts.get("data", [])) > 0:
        first_account_id = accounts["data"][0]["id"]
        balance = float(accounts["data"][0]["balance"]["amount"])
        logger.info(f"Account balance: {balance}")
        result = place_dynamic_order(first_account_id, "buy", "BTC-USD", balance)
        logger.info(result)
