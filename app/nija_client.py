# app/nija_client.py
import os
import time
import requests
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import jwt

# simple stdout logger (so logs show in platform logs)
logger.remove()
logger.add(lambda msg: print(msg, end=""), level=os.getenv("LOG_LEVEL", "INFO"))

class CoinbaseClient:
    """
    Coinbase Advanced Service Key (JWT ES256) client.
    Requires COINBASE_ISS and COINBASE_PEM_CONTENT env vars.
    """

    def __init__(self, advanced=True):
        self.advanced = advanced
        self.iss = os.getenv("COINBASE_ISS")
        self.pem_content = os.getenv("COINBASE_PEM_CONTENT")
        # base default to CDP (Coinbase Advanced). Allow override with COINBASE_BASE.
        self.base_url = os.getenv("COINBASE_BASE", "https://api.cdp.coinbase.com" if advanced else "https://api.coinbase.com/v2")

        if not self.iss or not self.pem_content:
            raise ValueError("COINBASE_ISS or COINBASE_PEM_CONTENT missing in environment")

        self.token = self._generate_jwt()
        logger.info(f"CoinbaseClient initialized. Advanced={self.advanced}, base={self.base_url}")

    def _generate_jwt(self):
        """
        Load PEM private key and return signed ES256 JWT string.
        """
        try:
            private_key = serialization.load_pem_private_key(
                self.pem_content.encode(),
                password=None,
                backend=default_backend()
            )
            payload = {"iss": self.iss, "iat": int(time.time()), "exp": int(time.time()) + 300}
            token = jwt.encode(payload, private_key, algorithm="ES256")
            # pyjwt sometimes returns bytes
            if isinstance(token, bytes):
                token = token.decode()
            return token
        except Exception as e:
            logger.exception(f"JWT generation failed: {e}")
            raise

    def request(self, method="GET", path="/v3/accounts", json_body=None):
        """
        Generic request helper. path should include leading slash and appropriate version (eg /v3/accounts).
        Returns (status_code, parsed_json_or_none).
        """
        url = self.base_url.rstrip("/") + path
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        try:
            resp = requests.request(method, url, headers=headers, json=json_body, timeout=10)
            try:
                data = resp.json()
            except Exception:
                data = None
            return resp.status_code, data
        except Exception as e:
            logger.exception(f"HTTP request failed: {e}")
            return None, None

    def fetch_advanced_accounts(self):
        """
        Call v3 /accounts for Advanced (CDP). Returns list or [].
        """
        status, data = self.request("GET", "/v3/accounts")
        if status == 404:
            logger.warning("/v3/accounts returned 404 (not found).")
            return []
        if status != 200 or not isinstance(data, dict):
            logger.error(f"❌ Failed to fetch accounts. Status: {status} Body: {data}")
            return []
        accounts = data.get("data", []) if isinstance(data, dict) else []
        logger.info(f"✅ Fetched {len(accounts)} accounts.")
        return accounts
