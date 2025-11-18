# nija_bot.py
import os
import time
import requests
import jwt
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from nija_client import get_coinbase_client

# -------------------------
# Load environment variables
# -------------------------
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_API_SECRET = os.environ.get("COINBASE_API_SECRET")
COINBASE_PEM_CONTENT = os.environ.get("COINBASE_PEM_CONTENT")
COINBASE_ORG_ID = os.environ.get("COINBASE_ORG_ID")

# -------------------------
# Load PEM
# -------------------------
PEM_KEY = None
if COINBASE_PEM_CONTENT:
    try:
        PEM_KEY = serialization.load_pem_private_key(
            COINBASE_PEM_CONTENT.encode(),
            password=None,
            backend=default_backend()
        )
        logger.info("✅ PEM loaded successfully")
    except Exception as e:
        logger.error(f"❌ Failed to load PEM: {e}")

# -------------------------
# JWT generator
# -------------------------
def generate_jwt():
    if PEM_KEY is None or not COINBASE_ORG_ID:
        logger.warning("JWT cannot be generated — missing PEM or ORG ID")
        return None
    payload = {
        "iat": int(time.time()),
        "exp": int(time.time()) + 30,
        "sub": COINBASE_ORG_ID
    }
    try:
        token = jwt.encode(payload, PEM_KEY, algorithm="ES256")
        logger.info("✅ JWT generated successfully")
        return token
    except Exception as e:
        logger.error(f"❌ JWT generation failed: {e}")
        return None

# -------------------------
# Safe requests with retries
# -------------------------
def safe_request(method, url, headers=None, data=None, max_retries=3, **kwargs):
    for attempt in range(max_retries):
        try:
            response = requests.request(method, url, headers=headers, data=data, **kwargs)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.warning(f"Request failed (attempt {attempt+1}/{max_retries}): {e}")
            time.sleep(2)
    logger.error("Max retries reached, request failed")
    return None

# -------------------------
# Fetch funded accounts
# -------------------------
def fetch_funded_accounts(client):
    try:
        accounts = client.get_accounts()
        funded = [a for a in accounts if float(a.get("balance", 0)) > 0]
        logger.info(f"✅ Funded accounts: {funded}")
        return funded
    except Exception as e:
        logger.warning(f"Failed to fetch accounts: {e}")
        return []

# -------------------------
# Main bot logic
# -------------------------
def main():
    logger.info("Starting Nija bot...")
    
    # Instantiate Coinbase client (live or mock)
    client = get_coinbase_client(
        api_key=COINBASE_API_KEY,
        api_secret=COINBASE_API_SECRET,
        pem=COINBASE_PEM_CONTENT,
        org_id=COINBASE_ORG_ID
    )

    # Fetch funded accounts
    funded_accounts = fetch_funded_accounts(client)

    # Example trading logic (replace with your signals/strategy)
    for acct in funded_accounts:
        logger.info(f"Processing account {acct['id']} with balance {acct['balance']}")
        try:
            order = client.place_order(
                product_id="BTC-USD",
                side="buy",
                price="50000",
                size="0.001"
            )
            logger.info(f"Order placed: {order}")
        except Exception as e:
            logger.warning(f"Order failed or dry-run: {e}")

    logger.info("Bot run finished.")

# -------------------------
# Entry point
# -------------------------
if __name__ == "__main__":
    main()
