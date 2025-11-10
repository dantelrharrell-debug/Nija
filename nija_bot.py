import os
import time
import requests
from loguru import logger
import jwt  # PyJWT required

# Load environment variables
API_KEY = os.getenv("COINBASE_API_KEY")          # Classic API key (optional fallback)
API_SECRET = os.getenv("COINBASE_API_SECRET")    # Classic API secret
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")  # For JWT

# Coinbase Advanced base URL (correct per docs)
BASE_ADV = "https://api.coinbase.com"

class NijaClient:
    def __init__(self):
        self.jwt = None
        self._init_jwt()

    def _init_jwt(self):
        if not COINBASE_PEM_CONTENT:
            logger.warning("No PEM content found, skipping JWT setup")
            return

        # Generate ephemeral JWT (mirror Coinbase docs)
        payload = {
            "sub": "YOUR_CLIENT_ID_OR_EMAIL",  # replace with your client id/email if required
            "iat": int(time.time()),
            "exp": int(time.time()) + 60,  # 1 minute expiration
        }
        self.jwt = jwt.encode(payload, COINBASE_PEM_CONTENT, algorithm="ES256")
        logger.info("Generated ephemeral JWT")

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.jwt}",
            "CB-VERSION": "2025-11-09",  # Current API version
            "Content-Type": "application/json",
        }

    def fetch_accounts(self):
        if not self.jwt:
            logger.error("JWT not set — cannot fetch Advanced API accounts")
            return []

        url = f"{BASE_ADV}/api/v3/brokerage/accounts"
        try:
            resp = requests.get(url, headers=self._headers(), timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                logger.info("Fetched accounts successfully via Advanced API")
                return data.get("accounts", [])
            else:
                logger.error(f"Advanced API returned {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.error(f"Exception fetching accounts: {e}")
        return []

if __name__ == "__main__":
    logger.info("Starting Nija bot — LIVE mode")
    client = NijaClient()

    attempts = 3
    for i in range(attempts):
        accounts = client.fetch_accounts()
        if accounts:
            for acc in accounts:
                logger.info(f"Account: {acc}")
            break
        else:
            sleep_time = 2 ** i
            logger.info(f"Retrying in {sleep_time} seconds (attempt {i+1}/{attempts})")
            time.sleep(sleep_time)
    else:
        logger.error("All retries failed — no accounts fetched")
