import os
import time
import requests
import jwt
from loguru import logger
import threading

class NijaClient:
    POSSIBLE_ENDPOINTS = [
        "/api/v3/brokerage/accounts",
        "/accounts",
        "/brokerage/accounts"
    ]

    def __init__(self):
        self.base = os.getenv("COINBASE_BASE", "https://api.cdp.coinbase.com")
        self.pem = os.getenv("COINBASE_PEM_CONTENT")
        self.iss = os.getenv("COINBASE_ISS")
        if not all([self.base, self.pem, self.iss]):
            logger.error("Missing COINBASE_BASE, COINBASE_PEM_CONTENT, or COINBASE_ISS")
            raise SystemExit(1)

        self.jwt_token = None
        self.active_endpoint = None  # Will store working endpoint
        self._generate_jwt()
        self._start_jwt_refresh()
        logger.info(f"NIJA-CLIENT-READY: base={self.base} jwt_set={self.jwt_token is not None}")

    def _generate_jwt(self):
        now = int(time.time())
        payload = {"iat": now, "exp": now + 300, "iss": self.iss}
        try:
            token = jwt.encode(payload, self.pem, algorithm="ES256")
            if isinstance(token, bytes):
                token = token.decode("utf-8")
            self.jwt_token = token
            logger.info("✅ JWT generated successfully")
        except Exception as e:
            logger.error(f"Failed to generate JWT: {e}")
            raise

    def _start_jwt_refresh(self):
        def refresh_loop():
            while True:
                time.sleep(240)
                self._generate_jwt()
        threading.Thread(target=refresh_loop, daemon=True).start()

    def _detect_endpoint(self):
        """Try endpoints one by one until one works."""
        headers = {"Authorization": f"Bearer {self.jwt_token}"}
        for path in self.POSSIBLE_ENDPOINTS:
            url = f"{self.base.rstrip('/')}{path}"
            try:
                r = requests.get(url, headers=headers, timeout=10)
                if r.status_code == 200:
                    logger.info(f"✅ Working endpoint found: {url}")
                    self.active_endpoint = path
                    return True
            except requests.RequestException:
                continue
        logger.error("❌ No valid endpoint found for Coinbase Advanced accounts")
        return False

    def fetch_accounts(self):
        if not self.jwt_token:
            logger.warning("JWT not set, cannot fetch accounts")
            return []

        # Detect endpoint if not already known
        if not self.active_endpoint:
            if not self._detect_endpoint():
                return []

        url = f"{self.base.rstrip('/')}{self.active_endpoint}"
        headers = {"Authorization": f"Bearer {self.jwt_token}"}
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                # Attempt to normalize response
                if "data" in data:
                    return data["data"]
                elif "accounts" in data:
                    return data["accounts"]
                else:
                    return [data]
            else:
                logger.error(f"Fetch accounts failed: {r.status_code} {r.text}")
                return []
        except requests.RequestException as e:
            logger.error(f"Request failed: {e}")
            return []

    def get_balances(self):
        accounts = self.fetch_accounts()
        if not accounts:
            logger.warning("No accounts fetched")
            return {}

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
