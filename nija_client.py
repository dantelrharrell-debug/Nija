import os
import time
import requests
import jwt
from loguru import logger
import threading

class NijaCoinbaseClient:
    """
    Coinbase client with Advanced (CDP) JWT support and automatic fallback to Standard API.
    """
    def __init__(self):
        self.base = os.getenv("COINBASE_BASE", "https://api.cdp.coinbase.com")
        self.pem = os.getenv("COINBASE_PEM_CONTENT")
        self.iss = os.getenv("COINBASE_ISS")
        self.jwt = None
        self.advanced_mode = bool(self.pem and self.iss)

        if self.advanced_mode:
            self._generate_jwt()
            self._start_jwt_refresh()
            logger.info("✅ Advanced JWT mode enabled")
        else:
            logger.info("ℹ️ Falling back to Standard API mode")

        logger.info(f"NIJA-CLIENT-READY: base={self.base} advanced={self.advanced_mode} jwt_set={bool(self.jwt)}")

    def _generate_jwt(self):
        now = int(time.time())
        payload = {"iat": now, "exp": now + 300, "iss": self.iss}
        try:
            token = jwt.encode(payload, self.pem, algorithm="ES256")
            if isinstance(token, bytes):
                token = token.decode("utf-8")
            self.jwt = token
            logger.info("✅ JWT generated successfully")
        except Exception as e:
            logger.error(f"Failed to generate JWT: {e}")
            self.jwt = None

    def _start_jwt_refresh(self):
        def refresh_loop():
            while True:
                time.sleep(240)
                self._generate_jwt()
        threading.Thread(target=refresh_loop, daemon=True).start()

    def _headers(self):
        if self.jwt:
            return {"Authorization": f"Bearer {self.jwt}", "Content-Type": "application/json"}
        return {"Content-Type": "application/json"}

    def fetch_accounts(self):
        """
        Try Advanced first, then fallback to Standard API.
        Returns list of account dicts or empty list.
        """
        urls = []
        if self.advanced_mode:
            urls.append(f"{self.base.rstrip('/')}/api/v3/brokerage/accounts")
        urls.append("https://api.coinbase.com/v2/accounts")  # standard fallback

        for url in urls:
            try:
                resp = requests.get(url, headers=self._headers(), timeout=15)
                if resp.status_code == 200:
                    data = resp.json()
                    # Detect account list keys
                    for key in ("accounts", "data", "account"):
                        if key in data and isinstance(data[key], list):
                            return data[key]
                    # If structure is different, wrap single dict
                    if "currency" in data and ("balance" in data or "available" in data):
                        return [data]
                    return []
                else:
                    logger.warning(f"Endpoint {url} returned {resp.status_code}")
            except Exception as e:
                logger.error(f"Request to {url} failed: {e}")
        logger.error("All endpoints failed — no accounts fetched")
        return []

    def get_balances(self):
        """
        Returns dict: {currency: balance}
        """
        accounts = self.fetch_accounts()
        out = {}
        for a in accounts:
            cur = a.get("currency") or a.get("asset")
            amt = None
            if isinstance(a.get("balance"), dict):
                amt = a["balance"].get("amount") or a["balance"].get("value")
            if amt is None:
                amt = a.get("available_balance") or a.get("available") or a.get("balance")
            try:
                out[cur] = float(amt or 0)
            except:
                out[cur] = 0.0
        return out
