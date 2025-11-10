import os
import time
import hmac
import hashlib
import requests
import jwt
from loguru import logger
import threading

class NijaClient:
    """
    Coinbase client supporting:
    - Advanced API (JWT from PEM/ISS)
    - Classic API fallback (API key/secret)
    """

    def __init__(self):
        # Advanced API base
        self.base = os.getenv("COINBASE_BASE", "https://api.cdp.coinbase.com")
        self.pem = os.getenv("COINBASE_PEM_CONTENT")
        self.iss = os.getenv("COINBASE_ISS")
        self.jwt_token = None

        # Init JWT if PEM/ISS exist
        if self.pem and self.iss:
            self._generate_jwt()
            self._start_jwt_refresh()
            logger.info(f"NIJA-CLIENT-READY: base={self.base} jwt_set={self.jwt_token is not None}")
        else:
            logger.warning("Advanced API credentials not found, will use Classic API fallback.")

    # ---------------- JWT / Advanced API ---------------- #
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
            self.jwt_token = None

    def _start_jwt_refresh(self):
        """Auto-refresh JWT every 4 minutes"""
        def refresh_loop():
            while True:
                time.sleep(240)
                self._generate_jwt()
        threading.Thread(target=refresh_loop, daemon=True).start()

    def _fetch_advanced_accounts(self):
        """Fetch accounts using Advanced API"""
        if not self.jwt_token:
            logger.warning("JWT not set, cannot fetch advanced accounts")
            return []

        url = f"{self.base.rstrip('/')}/api/v3/brokerage/accounts"
        headers = {"Authorization": f"Bearer {self.jwt_token}"}
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            # Handle standard response keys
            for key in ("accounts", "data"):
                if key in data and isinstance(data[key], list):
                    return data[key]
            return [data] if "currency" in data else []
        except requests.RequestException as e:
            logger.error(f"Advanced API request failed: {e}")
            return []

    # ---------------- Classic API fallback ---------------- #
    def _fetch_classic_accounts(self):
        """Fetch accounts using Classic API (API key/secret)"""
        API_KEY = os.getenv("COINBASE_API_KEY")
        API_SECRET = os.getenv("COINBASE_API_SECRET")
        if not all([API_KEY, API_SECRET]):
            logger.error("No Classic API credentials found")
            return []

        url = "https://api.coinbase.com/v2/accounts"
        timestamp = str(int(time.time()))
        message = timestamp + "GET" + "/v2/accounts"
        signature = hmac.new(
            API_SECRET.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()

        headers = {
            "CB-ACCESS-KEY": API_KEY,
            "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json"
        }

        try:
            r = requests.get(url, headers=headers, timeout=15)
            r.raise_for_status()
            return r.json().get("data", [])
        except requests.RequestException as e:
            logger.error(f"Classic API fetch failed: {e}")
            return []

    # ---------------- Unified fetch_accounts ---------------- #
    def fetch_accounts(self):
        """Fetch accounts using Advanced API if available, else fallback to Classic API"""
        if self.jwt_token:
            accounts = self._fetch_advanced_accounts()
            if accounts:
                return accounts
            else:
                logger.warning("Advanced API failed, falling back to Classic API")
        return self._fetch_classic_accounts()

    # ---------------- Get balances ---------------- #
    def get_balances(self):
        accounts = self.fetch_accounts()
        balances = {}
        for a in accounts:
            cur = a.get("currency") or a.get("asset")
            amt = 0

            # Try multiple keys for balance
            if isinstance(a.get("balance"), dict):
                amt = a["balance"].get("amount") or a["balance"].get("value") or 0
            else:
                amt = a.get("available_balance") or a.get("available") or a.get("balance") or 0

            try:
                balances[cur] = float(amt)
            except:
                balances[cur] = 0.0
        return balances

# Alias
NijaCoinbaseClient = NijaClient
