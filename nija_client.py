import os
import time
import requests
import jwt
from loguru import logger

class NijaClient:
    def __init__(self):
        # Base URLs
        self.base_advanced = "https://api.cdp.coinbase.com"
        self.base_classic = "https://api.coinbase.com"

        # JWT setup for Advanced API
        self.jwt = None
        self._init_jwt()

        # Classic API credentials
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")

        # Track which API works
        self.working_api = None  # "advanced" or "classic"

    def _init_jwt(self):
        pem = os.getenv("COINBASE_PEM_CONTENT")
        iss = os.getenv("COINBASE_ISS")
        if pem and iss:
            payload = {"iat": int(time.time()), "exp": int(time.time()) + 300, "iss": iss}
            token = jwt.encode(payload, pem, algorithm="ES256")
            if isinstance(token, bytes):
                token = token.decode("utf-8")
            self.jwt = token
            logger.info("JWT generated for Advanced API")
        else:
            logger.warning("No PEM or ISS provided — skipping Advanced API")

    def _headers_advanced(self):
        return {"Authorization": f"Bearer {self.jwt}"}

    def _headers_classic(self):
        timestamp = str(int(time.time()))
        return {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": self.api_secret,  # TODO: generate proper HMAC for live trades
            "CB-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json"
        }

    def fetch_accounts(self):
        # If we already know which API works, use it directly
        if self.working_api == "advanced" and self.jwt:
            return self._fetch_advanced()
        elif self.working_api == "classic" and self.api_key and self.api_secret:
            return self._fetch_classic()

        # 1️⃣ Try Advanced API
        if self.jwt:
            accounts = self._fetch_advanced()
            if accounts:
                self.working_api = "advanced"
                return accounts

        # 2️⃣ Try Classic API
        if self.api_key and self.api_secret:
            accounts = self._fetch_classic()
            if accounts:
                self.working_api = "classic"
                return accounts

        logger.error("No accounts fetched — both Advanced and Classic failed")
        return []

    def _fetch_advanced(self):
        try:
            url_adv = f"{self.base_advanced.rstrip('/')}/api/v3/brokerage/accounts"
            resp = requests.get(url_adv, headers=self._headers_advanced(), timeout=10)
            if resp.status_code == 200:
                logger.info("Fetched accounts from Advanced API")
                return resp.json().get("accounts", resp.json().get("data", []))
            else:
                logger.warning(f"Advanced API failed ({resp.status_code})")
        except Exception as e:
            logger.warning(f"Advanced API exception: {e}")
        return []

    def _fetch_classic(self):
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
        return []

    def get_balances(self):
        accounts = self.fetch_accounts()
        balances = [acct for acct in accounts if float(acct.get("balance", {}).get("amount", 0)) > 0]
        if not balances:
            logger.warning("No non-zero balances found")
        return balances


if __name__ == "__main__":
    logger.info("Starting Nija bot — LIVE mode")
    client = NijaClient()
    balances = client.get_balances()
    for b in balances:
        logger.info(f"Account: {b.get('name')} | Balance: {b.get('balance')}")
