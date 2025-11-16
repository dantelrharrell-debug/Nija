import os
import time
import requests
import jwt
from cryptography.hazmat.primitives import serialization
from loguru import logger

# ===========================
# Load environment variables
# ===========================
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")  # Full path
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")

# ===========================
# Load PEM private key
# ===========================
private_key = serialization.load_pem_private_key(
    COINBASE_PEM_CONTENT.encode(),
    password=None
)
logger.info("PEM private key loaded successfully")

# ===========================
# Function to generate a valid JWT
# ===========================
def generate_jwt():
    iat = int(time.time())
    exp = iat + 300  # 5-minute expiration
    uri_path = f"GET /api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"

    payload = {
        "sub": COINBASE_API_KEY,
        "iat": iat,
        "exp": exp,
        "uri": uri_path
    }

    token = jwt.encode(payload, private_key, algorithm="ES256")
    return token

# ===========================
# Function to fetch accounts with retry
# ===========================
def get_accounts():
    token = generate_jwt()
    headers = {"Authorization": f"Bearer {token}"}
    endpoints = [
        f"https://api.coinbase.com/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts",
        "https://api.coinbase.com/api/v3/brokerage/accounts"
    ]

    for url in endpoints:
        try:
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                logger.info(f"✅ Accounts fetched successfully from {url}")
                return response.json()
            else:
                logger.warning(f"❌ Failed to fetch accounts from {url}. Status: {response.status_code}")
                logger.warning(response.text)
        except Exception as e:
            logger.error(f"Exception fetching accounts from {url}: {e}")
    return None

# ===========================
# Main loop
# ===========================
def main_loop():
    logger.info("Nija bot starting...")
    while True:
        accounts = get_accounts()
        if accounts:
            # Process your accounts here, e.g., start trading
            logger.info(f"Accounts: {accounts}")
        else:
            logger.warning("Accounts fetch failed, retrying next heartbeat")
        time.sleep(5)  # heartbeat interval

if __name__ == "__main__":
    main_loop()
