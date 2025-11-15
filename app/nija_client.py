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

# --- Load Coinbase credentials from environment ---
COINBASE_ORG_ID = os.environ.get("COINBASE_ORG_ID")
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_PEM_PATH = os.environ.get("COINBASE_PEM_PATH")
LIVE_TRADING = os.environ.get("LIVE_TRADING", "0") == "1"

if not (COINBASE_ORG_ID and COINBASE_API_KEY and COINBASE_PEM_PATH):
    logger.error("Missing Coinbase credentials in environment variables.")
    raise ValueError("Missing Coinbase credentials")

# --- Load private key from PEM file ---
with open(COINBASE_PEM_PATH, "rb") as pem_file:
    pem_data = pem_file.read()
    private_key = serialization.load_pem_private_key(
        pem_data,
        password=None,
        backend=default_backend()
    )

# --- Generate JWT token ---
def generate_jwt():
    current_time = int(time.time())
    payload = {
        "sub": COINBASE_ORG_ID,
        "iat": current_time,
        "exp": current_time + 300  # 5 minutes expiration
    }

    headers = {
        "alg": "ES256",
        "kid": COINBASE_API_KEY
    }

    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
    return token

# --- Make test API request ---
def test_coinbase_connection():
    token = generate_jwt()
    headers = {"Authorization": f"Bearer {token}"}
    url = "https://api.coinbase.com/v2/accounts"

    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            logger.info("✅ Coinbase API connection successful")
            logger.info(response.json())
        else:
            logger.error(f"❌ Coinbase API error: {response.status_code} {response.text}")
    except Exception as e:
        logger.error(f"Exception during Coinbase API call: {e}")

# --- Run test if script is executed ---
if __name__ == "__main__":
    test_coinbase_connection()
