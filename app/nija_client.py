# app/nija_client.py
import os
import time
import requests
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import jwt

logger.remove()
logger.add(lambda msg: print(msg, end=""), level=os.getenv("LOG_LEVEL", "INFO"))

class CoinbaseClient:
    """
    Coinbase service-key (Advanced) client using JWT (ES256).
    Place this file at app/nija_client.py
    """
    def __init__(self, advanced=True):
        self.advanced = advanced
        self.iss = os.getenv("COINBASE_ISS")
        self.pem_content = os.getenv("COINBASE_PEM_CONTENT")
        # base (use CDP for advanced by default)
        self.base_url = os.getenv("COINBASE_BASE", "https://api.cdp.coinbase.com" if advanced else "https://api.coinbase.com/v2")

        if not self.iss or not self.pem_content:
            raise ValueError("COINBASE_ISS or COINBASE_PEM_CONTENT missing in environment")

        # generate token
        self.token = self._generate_jwt()
        logger.info(f"HMAC CoinbaseClient initialized. Advanced={self.advanced}, base={self.base_url}")

    def _generate_jwt(self):
        try:
            private_key = serialization.load_pem_private_key(
                self.pem_content.encode(),
                password=None,
                backend=default_backend()
            )
            payload = {
                "iss": self.iss,
                "iat": int(time.time()),
                "exp": int(time.time()) + 300
            }
            token = jwt.encode(payload, private_key, algorithm="ES256")
            # PyJWT returns bytes on older versions — always convert to str
            if isinstance(token, bytes):
                token = token.decode()
            return token
        except Exception as e:
            logger.exception("JWT generation failed")
            raise

    def request(self, method="GET", path="/v3/accounts"):
        url = self.base_url.rstrip("/") + path
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        try:
            resp = requests.request(method, url, headers=headers, timeout=10)
            try:
                data = resp.json()
            except Exception:
                data = None
            return resp.status_code, data
        except Exception as e:
            logger.exception("HTTP request failed")
            return None, None

    def fetch_advanced_accounts(self):
        """
        Strictly calls the v3 /accounts (CDP) endpoint. Returns list of accounts or [].
        """
        status, data = self.request("GET", "/v3/accounts")
        if status == 404:
            logger.warning("/v3/accounts returned 404 (not found).")
            return []
        if status != 200 or not data:
            logger.error(f"❌ Failed to fetch accounts. Status: {status} Body: {data}")
            return []
        accounts = data.get("data", []) if isinstance(data, dict) else []
        logger.info(f"✅ Fetched {len(accounts)} accounts.")
        return accounts
