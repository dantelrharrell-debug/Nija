import os
import time
import requests
import jwt
from loguru import logger

class NijaClient:
    def __init__(self, api_key=None, api_secret=None, pem_content=None, live=True):
        self.api_key = api_key or os.getenv("COINBASE_API_KEY")
        self.api_secret = api_secret or os.getenv("COINBASE_API_SECRET")
        self.pem_content = pem_content or os.getenv("COINBASE_PEM_CONTENT")
        self.live = live

        # Correct Coinbase endpoints
        self.base_advanced = "https://api.coinbase.com/brokerage/v1"
        self.base_classic = "https://api.coinbase.com/v2"

        self.jwt = None
        if self.pem_content:
            self._init_jwt()
            self._start_jwt_refresh()

        logger.info(f"nija_client init: base={self.base_advanced} advanced={self.jwt is not None} jwt_set={self.jwt is not None}")

    # ---------------- JWT Handling ----------------
    def _init_jwt(self):
        try:
            payload = {
                "iat": int(time.time()),
                "exp": int(time.time()) + 300,  # 5 min expiration
                "sub": "nija-client"
            }
            self.jwt = jwt.encode(payload, self.pem_content, algorithm="ES256")
            logger.info("Generated ephemeral JWT from COINBASE_PEM_CONTENT")
        except Exception as e:
            logger.error(f"Failed to generate JWT: {e}")
            self.jwt = None

    def _start_jwt_refresh(self):
        # In production, run in a background thread or async loop
        def refresh_loop():
            while True:
                time.sleep(240)
                self._init_jwt()
        import threading
        t = threading.Thread(target=refresh_loop, daemon=True)
        t.start()
        logger.info("JWT auto-refresh started: every 240 seconds")

    def _headers_advanced(self):
        return {"Authorization": f"Bearer {self.jwt}"} if self.jwt else {}

    def _headers_classic(self):
        return {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": self.api_secret  # For simplicity; in production compute HMAC signature
        }

    # ---------------- Fetch Accounts ----------------
    def fetch_accounts(self):
        # 1️⃣ Try Advanced API
        if self.jwt:
            try:
                url_adv = f"{self.base_advanced}/accounts"
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
                    url_classic = f"{self.base_classic}/accounts"
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

    # ---------------- Fetch Balances ----------------
    def get_balances(self):
        accounts = self.fetch_accounts()
        non_zero = []
        for acct in accounts:
            balance = float(acct.get("balance", {}).get("amount", 0))
            if balance > 0:
                non_zero.append({
                    "id": acct.get("id"),
                    "currency": acct.get("balance", {}).get("currency"),
                    "balance": balance
                })
        if not non_zero:
            logger.warning("No non-zero balances found")
        return non_zero

# ---------------- Example Usage ----------------
if __name__ == "__main__":
    client = NijaClient()
    accounts = client.fetch_accounts()
    logger.info(f"Accounts fetched: {accounts}")
    balances = client.get_balances()
    logger.info(f"Non-zero balances: {balances}")
