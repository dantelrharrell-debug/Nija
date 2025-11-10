import os
import time
import requests
import jwt
from loguru import logger

class CoinbaseClient:
    def __init__(self, advanced=True, base=None):
        self.advanced = advanced
        # Set the base URL from env or default to Advanced API base
        self.base = base or os.getenv(
            "COINBASE_ADVANCED_BASE", "https://api.prime.coinbase.com"
        )
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
                # Don't spam logs; only warn once per endpoint
                logger.warning(f"{endpoint} returned 404 Not Found")
                return None
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            logger.warning(f"HTTP request failed for {endpoint}: {e}")
            return None

    def fetch_advanced_accounts(self):
        """
        Fetch accounts using only endpoints valid for this key.
        Stops at the first endpoint that returns valid data.
        """
        # Candidate endpoints (order matters: most likely first)
        candidate_endpoints = [
            "/accounts",             # standard Advanced / Prime account
            "/v2/accounts",          # v2 API
            "/brokerage/accounts",   # if key has brokerage access
            "/api/v3/trading/accounts",
            "/api/v3/portfolios"
        ]

        for ep in candidate_endpoints:
            data = self._request("GET", ep)
            if data:
                logger.info(f"Accounts fetched successfully from endpoint: {ep}")
                return data
            else:
                logger.warning(f"{ep} returned no data or failed")

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
