import os
import time
import requests
import jwt
from loguru import logger

# ===============================
# Environment & API Setup
# ===============================
BASE_ADVANCED = "https://api.cdp.coinbase.com"
BASE_CLASSIC = "https://api.coinbase.com"

COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")
COINBASE_ISS = os.getenv("COINBASE_ISS")
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")

# Generate ephemeral JWT for Advanced API
jwt_token = None
if COINBASE_PEM_CONTENT and COINBASE_ISS:
    payload = {"iat": int(time.time()), "exp": int(time.time()) + 300, "iss": COINBASE_ISS}
    jwt_token = jwt.encode(payload, COINBASE_PEM_CONTENT, algorithm="ES256")
    if isinstance(jwt_token, bytes):
        jwt_token = jwt_token.decode("utf-8")
    logger.info("Generated ephemeral JWT for Advanced API")
else:
    logger.warning("No PEM content or ISS found — Advanced API will be unavailable")

# ===============================
# Nija Client Class
# ===============================
class NijaClient:
    def __init__(self, base_advanced, base_classic, jwt_token=None, api_key=None, api_secret=None):
        self.base_advanced = base_advanced
        self.base_classic = base_classic
        self.jwt = jwt_token
        self.api_key = api_key
        self.api_secret = api_secret

    # Advanced API headers
    def _headers_advanced(self):
        return {"Authorization": f"Bearer {self.jwt}"}

    # Classic API headers
    def _headers_classic(self):
        timestamp = str(int(time.time()))
        return {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": self.api_secret,  # replace with proper HMAC if needed
            "CB-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json"
        }

    # Fetch accounts with Advanced -> Classic fallback
    def fetch_accounts(self):
        # 1️⃣ Try Advanced API once
        if self.jwt:
            try:
                url_adv = f"{self.base_advanced.rstrip('/')}/api/v3/brokerage/accounts"
                resp = requests.get(url_adv, headers=self._headers_advanced(), timeout=10)
                if resp.status_code == 200:
                    logger.info("Fetched accounts from Advanced API")
                    return resp.json().get("accounts", resp.json().get("data", []))
                else:
                    logger.warning(f"Advanced API failed ({resp.status_code}), switching to Classic API")
            except Exception as e:
                logger.warning(f"Advanced API exception: {e}, switching to Classic API")

        # 2️⃣ Try Classic API with retries
        if self.api_key and self.api_secret:
            for attempt in range(3):
                try:
                    url_classic = f"{self.base_classic.rstrip('/')}/v2/accounts"
                    resp = requests.get(url_classic, headers=self._headers_classic(), timeout=10)
                    if resp.status_code == 200:
                        logger.info("Fetched accounts from Classic API")
                        return resp.json().get("data", [])
                    else:
                        logger.warning(f"Classic API attempt {attempt+1} failed: {resp.status_code}")
                except Exception as e:
                    logger.warning(f"Classic API attempt {attempt+1} exception: {e}")
                time.sleep(2 ** attempt)  # exponential backoff

        logger.error("No accounts fetched — both Advanced and Classic failed")
        return []

# ===============================
# Bot Startup
# ===============================
def main():
    logger.info("Starting Nija bot — LIVE mode")
    nija = NijaClient(
        base_advanced=BASE_ADVANCED,
        base_classic=BASE_CLASSIC,
        jwt_token=jwt_token,
        api_key=API_KEY,
        api_secret=API_SECRET
    )

    accounts = nija.fetch_accounts()
    if accounts:
        logger.info(f"Accounts fetched: {accounts}")
        # Optionally, log balances
        for acc in accounts:
            logger.info(f"Account: {acc.get('id', acc.get('name'))} | Balance: {acc.get('balance', acc.get('currency', 'N/A'))}")
    else:
        logger.warning("No accounts available or fetched.")

if __name__ == "__main__":
    main()
