import os
import time
import requests
import jwt
from loguru import logger

class NijaClient:
    def __init__(self):
        self.base = os.getenv("COINBASE_BASE", "https://api.coinbase.com")  # Standard base
        self.pem = os.getenv("COINBASE_PEM_CONTENT")
        self.iss = os.getenv("COINBASE_ISS")
        self.jwt_token = None
        self.use_advanced = False

        if self.pem and self.iss:
            self.use_advanced = True
            self._generate_jwt()
            self._start_jwt_refresh()
            logger.info(f"NIJA-CLIENT-READY: base={self.base} advanced=True jwt_set={self.jwt_token is not None}")
        else:
            logger.warning("Advanced JWT not set — will use standard API keys")

    def _generate_jwt(self):
        now = int(time.time())
        payload = {"iat": now, "exp": now + 300, "iss": self.iss}
        token = jwt.encode(payload, self.pem, algorithm="ES256")
        if isinstance(token, bytes):
            token = token.decode("utf-8")
        self.jwt_token = token
        logger.info("✅ JWT generated successfully")

    def _start_jwt_refresh(self):
        import threading
        def refresh_loop():
            while True:
                time.sleep(240)
                self._generate_jwt()
        threading.Thread(target=refresh_loop, daemon=True).start()

    def fetch_accounts(self):
        """Try Advanced API first, fallback to standard v2/accounts if 404."""
        if self.use_advanced and self.jwt_token:
            url = f"{self.base.rstrip('/')}/api/v3/brokerage/accounts"
            headers = {"Authorization": f"Bearer {self.jwt_token}"}
            try:
                resp = requests.get(url, headers=headers, timeout=10)
                if resp.status_code == 200:
                    logger.info("Advanced API accounts fetched")
                    return resp.json().get("data", [])
                elif resp.status_code == 404:
                    logger.warning("Advanced endpoint not found, falling back to standard API")
                else:
                    logger.error(f"Advanced API failed: {resp.status_code} {resp.text}")
            except Exception as e:
                logger.error(f"Advanced API request error: {e}")

        # Fallback to standard API
        url = f"{self.base.rstrip('/')}/v2/accounts"
        headers = {}  # Add API Key/Secret if needed for standard API
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                logger.info("Standard API accounts fetched")
                return resp.json().get("data", [])
            else:
                logger.error(f"Standard API failed: {resp.status_code} {resp.text}")
        except Exception as e:
            logger.error(f"Standard API request error: {e}")

        return []

    def get_balances(self):
        accounts = self.fetch_accounts()
        balances = {}
        for acc in accounts:
            cur = acc.get("currency") or acc.get("asset")
            amt = None
            if isinstance(acc.get("balance"), dict):
                amt = acc["balance"].get("amount") or acc["balance"].get("value")
            if amt is None:
                amt = acc.get("available_balance") or acc.get("available") or acc.get("balance")
            try:
                balances[cur] = float(amt or 0)
            except:
                balances[cur] = 0.0
        return balances
