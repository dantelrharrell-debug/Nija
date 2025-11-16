# -----------------------------
# main.py
# -----------------------------

import os
import time
import requests
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import jwt

# -----------------------------
# Load environment variables
# -----------------------------
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_PEM_PATH = os.getenv("COINBASE_PEM_PATH")
LIVE_TRADING = int(os.getenv("LIVE_TRADING", 0))

if not all([COINBASE_API_KEY, COINBASE_ORG_ID, COINBASE_PEM_PATH]):
    logger.error("Missing Coinbase configuration in environment variables!")
    exit(1)

# -----------------------------
# Load PEM private key
# -----------------------------
try:
    with open(COINBASE_PEM_PATH, "rb") as key_file:
        private_key = serialization.load_pem_private_key(
            key_file.read(),
            password=None,
            backend=default_backend()
        )
    logger.info("PEM private key loaded successfully")
except Exception as e:
    logger.error(f"Failed to load PEM private key: {e}")
    exit(1)

# -----------------------------
# Generate Coinbase JWT
# -----------------------------
def generate_jwt():
    try:
        payload = {
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,  # 5 minutes
            "sub": COINBASE_API_KEY,
        }
        token = jwt.encode(payload, private_key, algorithm="ES256")
        return token
    except Exception as e:
        logger.error(f"Failed to generate JWT: {e}")
        return None

# -----------------------------
# Fetch Coinbase accounts
# -----------------------------
def get_accounts():
    jwt_token = generate_jwt()
    if not jwt_token:
        logger.error("Cannot fetch accounts without JWT")
        return None
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "CB-VERSION": "2025-11-15"
    }
    url = f"https://api.coinbase.com/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        accounts = resp.json()
        return accounts
    except requests.HTTPError as e:
        logger.error(f"HTTP error fetching accounts: {e} | Response: {resp.text}")
    except Exception as e:
        logger.error(f"Unexpected error fetching accounts: {e}")
    return None

# -----------------------------
# Main loop
# -----------------------------
def main_loop():
    logger.info("Nija bot starting...")
    while True:
        accounts = get_accounts()
        if accounts:
            logger.info(f"Accounts fetched: {accounts}")
        else:
            logger.warning("Accounts fetch failed, retrying next heartbeat")
        time.sleep(5)  # heartbeat interval in seconds

if __name__ == "__main__":
    main_loop()
