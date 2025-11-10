import os
import time
import requests
import json
from loguru import logger

logger.remove()
logger.add(lambda msg: print(msg, end=""), level=os.getenv("LOG_LEVEL", "INFO"))

class CoinbaseClient:
    """
    Robust Coinbase client for Advanced (JWT/service key) and Classic (HMAC) APIs.
    """
    def __init__(self, advanced=True, debug=True):
        self.debug = debug
        self.advanced = advanced

        # Base URL selection
        if self.advanced:
            self.base_url = os.getenv("COINBASE_ADVANCED_BASE", "https://api.cdp.coinbase.com")
        else:
            self.base_url = os.getenv("COINBASE_BASE", "https://api.coinbase.com")

        # Load keys
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.iss = os.getenv("COINBASE_ISS")
        self.pem_content = os.getenv("COINBASE_PEM_CONTENT")

        # Track failed endpoints
        self.failed_endpoints = set()

        logger.info(f"CoinbaseClient initialized. advanced={self.advanced} base={self.base_url} debug={self.debug}")

    def _request(self, method="GET", path="/", headers=None, json_body=None):
        """
        Simple HTTP request wrapper.
        """
        url = self.base_url.rstrip("/") + path
        hdrs = headers or {"Accept": "application/json"}

        try:
            r = requests.request(method, url, headers=hdrs, json=json_body, timeout=10)
            if self.debug:
                logger.info(f"[DEBUG] {method} {url} -> {r.status_code} {r.text}")
            try:
                data = r.json() if r.content else None
            except json.JSONDecodeError:
                data = r.text
            return r.status_code, data
        except Exception as e:
            logger.warning(f"HTTP request failed for {url}: {e}")
            return None, None

    def fetch_accounts(self):
        """
        Try standard endpoints to get accounts; return empty list if none work.
        """
        paths = ["/v3/accounts", "/v2/accounts", "/v2/brokerage/accounts", "/accounts"]
        for path in paths:
            if path in self.failed_endpoints:
                continue
            status, data = self._request("GET", path)
            if status == 200 and data:
                return data.get("data", data) if isinstance(data, dict) else data
            self.failed_endpoints.add(path)
        logger.warning("No accounts endpoint succeeded.")
        return []

    def test_connection(self):
        """
        Quick check to ensure Nija can talk to Coinbase.
        """
        accounts = self.fetch_accounts()
        if accounts:
            logger.info(f"Connection OK: Found {len(accounts)} accounts")
            return True
        else:
            logger.warning("Connection failed: No accounts returned")
            return False


# Quick test if run directly
if __name__ == "__main__":
    client = CoinbaseClient(advanced=True, debug=True)
    if client.test_connection():
        accounts = client.fetch_accounts()
        print("Fetched accounts:", accounts)
    else:
        print("Could not connect to Coinbase API")
