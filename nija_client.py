import os
import time
import requests
import jwt
from loguru import logger
import threading
import hmac
import hashlib

class NijaCoinbaseClient:
    """
    Coinbase client supporting:
    - Advanced (CDP) mode via JWT
    - Standard API fallback via API key/secret/passphrase
    Debug mode prints all URLs and responses for troubleshooting.
    """
    def __init__(self, debug=False):
        # Base URLs
        self.base_advanced = os.getenv("COINBASE_BASE", "https://api.cdp.coinbase.com")
        self.base_standard = "https://api.coinbase.com"

        # Advanced (CDP) JWT credentials
        self.pem = os.getenv("COINBASE_PEM_CONTENT")
        self.iss = os.getenv("COINBASE_ISS")
        self.jwt = None

        # Standard API credentials
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE", "")

        self.debug = debug

        if not ((self.pem and self.iss) or (self.api_key and self.api_secret)):
            logger.error("Missing credentials: need either Advanced JWT or Standard API keys")
            raise SystemExit(1)

        self.advanced_mode = bool(self.pem and self.iss)
        if self.advanced_mode:
            self._init_jwt()
            self._start_jwt_refresh()

        logger.info(f"NIJA-CLIENT-READY: advanced={self.advanced_mode}, jwt_set={bool(self.jwt)}, debug={self.debug}")

    # ---------------- Advanced JWT ----------------
    def _init_jwt(self):
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
            self.advanced_mode = False

    def _start_jwt_refresh(self):
        def refresh_loop():
            while True:
                time.sleep(240)
                self._init_jwt()
        threading.Thread(target=refresh_loop, daemon=True).start()

    def _advanced_headers(self):
        if self.jwt:
            return {"Authorization": f"Bearer {self.jwt}", "Content-Type": "application/json"}
        return {}

    # ---------------- Standard API ----------------
    def _standard_headers(self, method="GET", path="/v2/accounts", body=""):
        timestamp = str(int(time.time()))
        message = timestamp + method + path + body
        signature = hmac.new(
            self.api_secret.encode(), message.encode(), hashlib.sha256
        ).hexdigest()
        return {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "CB-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json"
        }

    # ---------------- Fetch Accounts ----------------
    def fetch_accounts(self):
        # Try Advanced first
        if self.advanced_mode and self.jwt:
            urls = [
                f"{self.base_advanced.rstrip('/')}/api/v3/brokerage/accounts",
                f"{self.base_advanced.rstrip('/')}/accounts"
            ]
            for url in urls:
                try:
                    r = requests.get(url, headers=self._advanced_headers(), timeout=15)
                    if self.debug:
                        logger.debug(f"[Advanced] GET {url} → {r.status_code}: {r.text}")
                    if r.status_code == 200:
                        data = r.json()
                        return data.get("data") or data.get("accounts") or []
                except Exception as e:
                    logger.warning(f"[Advanced] fetch failed for {url}: {e}")
            logger.warning("Advanced endpoints failed — falling back to Standard API")
            self.advanced_mode = False

        # Standard API fallback
        url = f"{self.base_standard}/v2/accounts"
        try:
            r = requests.get(url, headers=self._standard_headers(), timeout=15)
            if self.debug:
                logger.debug(f"[Standard] GET {url} → {r.status_code}: {r.text}")
            r.raise_for_status()
            data = r.json()
            return data.get("data") or []
        except Exception as e:
            logger.error(f"Standard API fetch failed: {e}")
            return []

    # ---------------- Get Balances ----------------
    def get_balances(self):
        accounts = self.fetch_accounts()
        balances = {}
        for a in accounts:
            cur = a.get("currency") or a.get("asset")
            amt = None
            # Advanced format
            if isinstance(a.get("balance"), dict):
                amt = a["balance"].get("amount") or a["balance"].get("value")
            # Standard format
            if amt is None:
                amt = a.get("available_balance") or a.get("available") or a.get("balance")
            try:
                balances[cur] = float(amt or 0)
            except:
                balances[cur] = 0.0
        return balances

# Alias for consistency
__all__ = ["NijaCoinbaseClient"]
