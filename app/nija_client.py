import os
import time
import requests
import jwt
from loguru import logger

class CoinbaseClient:
    def __init__(self, advanced=True, base=None):
        self.advanced = advanced
        self.base = base or os.getenv("COINBASE_ADVANCED_BASE", "https://api.cdp.coinbase.com")
        self.iss = os.getenv("COINBASE_ISS")  # key identifier
        self.pem_content = os.getenv("COINBASE_PEM_CONTENT", "").replace("\\n", "\n")
        self.token = None

        if not self.pem_content or not self.iss:
            raise ValueError("Missing COINBASE_ISS or COINBASE_PEM_CONTENT env vars")

        self._generate_jwt()
        logger.info(f"CoinbaseClient initialized. advanced={self.advanced} base={self.base}")

    def _generate_jwt(self):
        """Generate JWT for authentication"""
        payload = {
            "iss": self.iss,
            "iat": int(time.time()),
            "exp": int(time.time()) + 300
        }
        try:
            self.token = jwt.encode(payload, self.pem_content, algorithm="ES256")
        except Exception as e:
            logger.error(f"Failed to generate JWT: {e}")
            raise

    def _request(self, method, endpoint, **kwargs):
        url = self.base.rstrip("/") + endpoint
        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            r = requests.request(method, url, headers=headers, **kwargs)
            if r.status_code == 404:
                logger.warning(f"HTTP request failed for {url}: 404 Not Found")
                return None
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            logger.warning(f"HTTP request failed for {url}: {e}")
            return None

    def fetch_advanced_accounts(self):
        """
        Fetch accounts using only verified Advanced API endpoints.
        Stops at the first endpoint that returns valid data.
        """
        endpoints = [
            "/accounts",         # main account info
            "/brokerage/accounts" # optional, if your key has brokerage access
        ]

        for ep in endpoints:
            data = self._request("GET", ep)
            if data:
                logger.info(f"Accounts fetched successfully from endpoint: {ep}")
                return data

        logger.error(
            "Failed to fetch accounts from all candidate endpoints. "
            "Check COINBASE_ADVANCED_BASE, API key permissions, and endpoint paths."
        )
        return None

    def validate_key(self):
        """Quick test to see if the key works"""
        data = self.fetch_advanced_accounts()
        if data is None:
            logger.error("API key invalid or base URL incorrect.")
            return False
        logger.info("API key validated successfully.")
        return True
