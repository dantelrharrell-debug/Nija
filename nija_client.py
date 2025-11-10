import os
import time
import requests
import jwt as pyjwt
from loguru import logger

class NijaCoinbaseClient:
    def __init__(self):
        # Base URLs
        self.base_advanced = os.getenv("COINBASE_BASE", "https://api.cdp.coinbase.com")
        self.base_classic = "https://api.coinbase.com"

        # Advanced JWT
        self.jwt = None
        pem = os.getenv("COINBASE_PEM_CONTENT")
        iss = os.getenv("COINBASE_ISS")
        if pem and iss:
            try:
                now = int(time.time())
                payload = {"iat": now, "exp": now + 300, "iss": iss}
                token = pyjwt.encode(payload, pem, algorithm="ES256")
                if isinstance(token, bytes):
                    token = token.decode("utf-8")
                self.jwt = token
                logger.info("✅ Generated ephemeral JWT from COINBASE_PEM_CONTENT")
            except Exception as e:
                logger.error(f"JWT generation failed: {e}")

        # Classic API keys
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")

        logger.info(f"NIJA-CLIENT-READY: advanced_jwt_set={bool(self.jwt)} classic_keys_set={bool(self.api_key and self.api_secret)}")

    def _headers_advanced(self):
        return {"Authorization": f"Bearer {self.jwt}", "Content-Type": "application/json"} if self.jwt else {}

    def _headers_classic(self):
        return {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": self.api_secret,  # NOTE: Proper HMAC required for live trading
            "CB-ACCESS-TIMESTAMP": str(int(time.time())),
            "Content-Type": "application/json"
        }

    def fetch_accounts(self):
        # --- Try Advanced first ---
        if self.jwt:
            try:
                url_adv = f"{self.base_advanced.rstrip('/')}/api/v3/brokerage/accounts"
                resp = requests.get(url_adv, headers=self._headers_advanced(), timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    # Returns list of accounts
                    for key in ("accounts", "data"):
                        if key in data and isinstance(data[key], list):
                            logger.info("✅ Fetched accounts from Advanced API")
                            return data[key]
                else:
                    logger.warning(f"Advanced API returned {resp.status_code}, falling back")
            except Exception as e:
                logger.warning(f"Advanced API fetch failed: {e}, falling back")

        # --- Fallback to Classic API ---
        if self.api_key and self.api_secret:
            try:
                url_classic = f"{self.base_classic.rstrip('/')}/v2/accounts"
                resp = requests.get(url_classic, headers=self._headers_classic(), timeout=10)
                if resp.status_code == 200:
                    logger.info("✅ Fetched accounts from Classic API")
                    return resp.json().get("data", [])
                else:
                    logger.error(f"Classic API fetch failed: {resp.status_code} {resp.text}")
            except Exception as e:
                logger.error(f"Classic API request failed: {e}")

        logger.error("No accounts fetched — both Advanced and Classic failed")
        return []

    def get_balances(self):
        accounts = self.fetch_accounts()
        balances = {}
        for acc in accounts:
            cur = acc.get("currency") or acc.get("asset")
            amt = None
            # Advanced structure
            if isinstance(acc.get("balance"), dict):
                amt = acc["balance"].get("amount") or acc["balance"].get("value")
            # Classic structure
            if amt is None:
                amt = acc.get("available_balance") or acc.get("available") or acc.get("balance")
            try:
                balances[cur] = float(amt or 0)
            except:
                balances[cur] = 0.0
        return balances
