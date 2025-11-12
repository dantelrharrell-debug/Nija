# nija_client.py
import os
import requests
import jwt
from loguru import logger
from datetime import datetime, timedelta

class CoinbaseClient:
    """
    Coinbase Advanced API client for Nija bot.
    Supports JWT authentication with PEM normalization.
    """

    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.base_url = os.getenv("COINBASE_BASE_URL", "https://api.coinbase.com")
        self.pem_content = self._load_pem()
        self.kid = os.getenv("COINBASE_JWT_KID")
        self.issuer = os.getenv("COINBASE_JWT_ISSUER")
        self.org_id = os.getenv("COINBASE_ORG_ID")

        if not self.api_key or not self.api_secret:
            logger.error("Coinbase API key or secret missing.")
            raise ValueError("Missing Coinbase credentials")
        logger.info("CoinbaseClient initialized")

    def _load_pem(self):
        pem = os.getenv("COINBASE_JWT_PEM", "")
        if not pem:
            logger.warning("No PEM provided, will fail JWT if needed")
            return None
        # Normalize line breaks
        pem = pem.replace("\\n", "\n") if "\\n" in pem else pem
        if not pem.startswith("-----BEGIN"):
            logger.error("PEM does not start with BEGIN line")
            raise ValueError("Malformed PEM")
        return pem

    def _get_jwt(self):
        if not self.pem_content:
            return None
        payload = {
            "iss": self.issuer,
            "iat": int(datetime.utcnow().timestamp()),
            "exp": int((datetime.utcnow() + timedelta(seconds=60)).timestamp()),
            "sub": self.org_id,
        }
        headers = {"kid": self.kid}
        try:
            token = jwt.encode(payload, self.pem_content, algorithm="ES256", headers=headers)
            return token
        except Exception as e:
            logger.error(f"Failed to generate JWT: {e}")
            raise

    def _headers(self):
        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-VERSION": "2025-11-01",
        }
        token = self._get_jwt()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _request(self, method, endpoint, data=None):
        url = f"{self.base_url}{endpoint}"
        headers = self._headers()
        try:
            r = requests.request(method, url, headers=headers, json=data)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error(f"HTTP request failed for {endpoint}: {e}")
            raise

    # Example method to get accounts
    def get_accounts(self):
        return self._request("GET", "/accounts")
