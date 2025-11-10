import os
import time
import requests
from loguru import logger
import jwt

class NijaClient:
    def __init__(self, base_advanced="https://api.coinbase.com", base_classic="https://api.coinbase.com",
                 api_key=None, api_secret=None, pem_content=None, advanced=True):
        self.base_advanced = base_advanced.rstrip("/")
        self.base_classic = base_classic.rstrip("/")
        self.api_key = api_key or os.getenv("COINBASE_API_KEY")
        self.api_secret = api_secret or os.getenv("COINBASE_API_SECRET")
        self.pem_content = pem_content or os.getenv("COINBASE_PEM_CONTENT")
        self.advanced = advanced
        self.jwt = None

        if self.pem_content and self.advanced:
            self._init_jwt()
            self._start_jwt_refresh()

        logger.info(f"nija_client init: base={self.base_advanced} advanced={self.advanced} jwt_set={self.jwt is not None}")
        print(f"NIJA-CLIENT-READY: base={self.base_advanced} jwt_set={self.jwt is not None}")

    # ---------------- JWT ----------------
    def _init_jwt(self):
        """Generate ephemeral JWT from PEM content"""
        try:
            payload = {
                "iat": int(time.time()),
                "exp": int(time.time()) + 240  # 4 minutes
            }
            self.jwt = jwt.encode(payload, self.pem_content, algorithm="ES256")
            logger.info("Generated ephemeral JWT from PEM content")
        except Exception as e:
            logger.error(f"JWT init failed: {e}")
            self.jwt = None

    def _start_jwt_refresh(self):
        """Auto-refresh JWT every 240 seconds"""
        def refresh_loop():
            while True:
                time.sleep(240)
                self._init_jwt()
        import threading
        threading.Thread(target=refresh_loop, daemon=True).start()

    def _headers_advanced(self):
        return {"Authorization": f"Bearer {self.jwt}", "CB-VERSION": "2025-11-09"}

    def _headers_classic(self):
        return {"CB-ACCESS-KEY": self.api_key, "CB-ACCESS-SIGN": self.api_secret, "CB-VERSION": "2025-11-09"}

    # ---------------- Fetch Accounts ----------------
    def fetch_accounts(self):
        # 1️⃣ Try Advanced API first
        if self.jwt and self.advanced:
            try:
                url_adv = f"{self.base_advanced}/api/v3/brokerage/accounts"
                resp = requests.get(url_adv, headers=self._headers_advanced(), timeout=10)
                if resp.status_code == 200:
                    logger.info("Fetched accounts from Advanced API")
                    return resp.json().get("accounts", resp.json().get("data", []))
                else:
                    logger.warning(f"Advanced API failed ({resp.status_code}), switching to Classic API")
            except Exception as e:
                logger.warning(f"Advanced API exception: {e}, switching to Classic API")

        # 2️⃣ Fallback to Classic API
        if self.api_key and self.api_secret:
            for attempt in range(3):
                try:
                    url_classic = f"{self.base_classic}/v2/accounts"
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
        if not accounts:
            logger.warning("No non-zero balances found")
            return []
        balances = []
        for acct in accounts:
            balance = acct.get("balance") or acct.get("native_balance") or {}
            if balance.get("amount") and float(balance["amount"]) > 0:
                balances.append({
                    "id": acct.get("id"),
                    "currency": balance.get("currency"),
                    "amount": balance.get("amount")
                })
        return balances

# ------------------- Usage -------------------
if __name__ == "__main__":
    client = NijaClient()
    accounts = client.fetch_accounts()
    print("Accounts:", accounts)
    balances = client.get_balances()
    print("Balances:", balances)
