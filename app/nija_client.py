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
logger.add(lambda m: print(m, end=""))

# --- Load environment variables ---
COINBASE_ORG_ID = os.environ.get("COINBASE_ORG_ID")
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_PEM_PATH = os.environ.get("COINBASE_PEM_PATH")

if not all([COINBASE_ORG_ID, COINBASE_API_KEY, COINBASE_PEM_PATH]):
    logger.error("Missing Coinbase credentials in environment variables")
    raise ValueError("COINBASE_ORG_ID, COINBASE_API_KEY, or COINBASE_PEM_PATH missing")

# --- Load private key from PEM file ---
with open(COINBASE_PEM_PATH, "rb") as pem_file:
    pem_data = pem_file.read()
    private_key = serialization.load_pem_private_key(
        pem_data,
        password=None,
        backend=default_backend()
    )

# --- Generate JWT ---
def generate_jwt():
    now = int(time.time())
    payload = {
        "sub": COINBASE_ORG_ID,
        "iat": now,
        "exp": now + 300  # 5 minutes expiration
    }
    token = jwt.encode(
        payload,
        private_key,
        algorithm="ES256",
        headers={"kid": COINBASE_API_KEY}
    )
    return token

# --- Prepare headers ---
def get_headers():
    token = generate_jwt()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    return headers

# --- Generic GET request with retries ---
def coinbase_get(url, retries=3, delay=1):
    for attempt in range(retries):
        headers = get_headers()
        response = requests.get(url, headers=headers)
        if response.status_code == 401:
            logger.warning(f"Unauthorized (401). Regenerating JWT and retrying... Attempt {attempt+1}/{retries}")
            time.sleep(delay)
            continue
        elif response.status_code != 200:
            logger.error(f"Coinbase API Error: {response.status_code} {response.text}")
        return response.json()
    logger.error("Failed to authenticate after multiple attempts")
    return None

# --- Generic POST request with retries ---
def coinbase_post(url, data, retries=3, delay=1):
    for attempt in range(retries):
        headers = get_headers()
        response = requests.post(url, json=data, headers=headers)
        if response.status_code == 401:
            logger.warning(f"Unauthorized (401). Regenerating JWT and retrying... Attempt {attempt+1}/{retries}")
            time.sleep(delay)
            continue
        elif response.status_code not in (200, 201):
            logger.error(f"Coinbase API Error: {response.status_code} {response.text}")
        return response.json()
    logger.error("Failed to authenticate after multiple attempts")
    return None

# --- Specific API endpoints ---
def get_accounts():
    url = "https://api.coinbase.com/v2/accounts"
    return coinbase_get(url)

def place_order(account_id, side, size, product_id):
    """
    Example POST order payload:
    side = 'buy' or 'sell'
    size = amount to trade
    product_id = trading pair, e.g., 'BTC-USD'
    """
    url = f"https://api.coinbase.com/v2/accounts/{account_id}/orders"
    data = {
        "type": "market",
        "side": side,
        "size": size,
        "product_id": product_id
    }
    return coinbase_post(url, data)

# --- For testing ---
if __name__ == "__main__":
    logger.info("Testing Coinbase API connection...")
    accounts = get_accounts()
    logger.info(accounts)

    # Example: place a test order
    if accounts and len(accounts.get("data", [])) > 0:
        first_account_id = accounts["data"][0]["id"]
        logger.info(f"Placing test order on account {first_account_id}...")
        result = place_order(first_account_id, "buy", "0.001", "BTC-USD")
        logger.info(result)
