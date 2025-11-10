# app/nija_client.py
import os
import time
import requests
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import jwt

class CoinbaseClient:
    """
    Minimal Coinbase Advanced (Service Key) client using JWT (ES256).
    Use COINBASE_ISS and COINBASE_PEM_CONTENT in environment.
    Optional: COINBASE_BASE (defaults to https://api.cdp.coinbase.com)
    """

    def __init__(self, advanced=True):
        self.advanced = advanced
        self.iss = os.getenv("COINBASE_ISS")
        self.pem_content = os.getenv("COINBASE_PEM_CONTENT")
        self.base_url = os.getenv("COINBASE_BASE", "https://api.cdp.coinbase.com")

        if not self.iss or not self.pem_content:
            raise ValueError("COINBASE_ISS or COINBASE_PEM_CONTENT missing in environment")

        # generate JWT
        self.token = self._generate_jwt()
        logger.info(f"HMAC CoinbaseClient initialized. Advanced={self.advanced} base={self.base_url}")

    def _generate_jwt(self):
        """
        Load PEM private key and sign a short lived JWT (ES256).
        """
        try:
            private_key = serialization.load_pem_private_key(
                self.pem_content.encode(),
                password=None,
                backend=default_backend()
            )
            payload = {
                "iss": self.iss,
                "iat": int(time.time()),
                "exp": int(time.time()) + 300  # 5 minutes
            }
            # PyJWT >= 2 returns str for encode. Use algorithm ES256.
            token = jwt.encode(payload, private_key, algorithm="ES256")
            if isinstance(token, bytes):
                token = token.decode()
            return token
        except Exception as e:
            logger.exception("JWT generation failed")
            raise

    def request(self, method="GET", path="/accounts", params=None, json_body=None):
        """
        Generic request helper. Returns (status_code, data_or_text).
        If response body is JSON, returns parsed JSON; otherwise returns raw text.
        """
        url = f"{self.base_url}{path}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        try:
            resp = requests.request(method, url, headers=headers, params=params, json=json_body, timeout=10)
        except Exception as e:
            logger.exception("HTTP request failed")
            return None, None

        # try to parse JSON; if not JSON, return text (helps debug 404 / HTML responses)
        try:
            data = resp.json()
        except Exception:
            data = resp.text

        return resp.status_code, data

    def fetch_advanced_accounts(self):
        """
        Strictly call v3/v2 /accounts depending on base_url.
        Returns list of accounts (possibly empty).
        """
        status, data = self.request("GET", "/v3/accounts" if "cdp.coinbase.com" in self.base_url else "/v2/accounts")
        if status != 200 or not data:
            logger.error(f"❌ Failed to fetch accounts. Status: {status} Body: {data}")
            return []
        # advanced API returns {"data": [...]}
        accounts = data.get("data") if isinstance(data, dict) else None
        if not accounts:
            logger.error(f"❌ Unexpected accounts response format: {data}")
            return []
        logger.info(f"✅ Fetched {len(accounts)} accounts.")
        return accounts
