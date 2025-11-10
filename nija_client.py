import os
import time
import requests
from loguru import logger

logger.remove()
logger.add(lambda msg: print(msg, end=""), level=os.getenv("LOG_LEVEL", "INFO"))

class CoinbaseClient:
    """
    Robust Coinbase client for Advanced (JWT/service key) and Classic (HMAC) APIs.
    """
    def __init__(self, advanced=True, debug=False):
        self.debug = debug
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.api_passphrase = os.getenv("COINBASE_API_PASSPHRASE", "")
        self.iss = os.getenv("COINBASE_ISS")
        self.pem_content = os.getenv("COINBASE_PEM_CONTENT")
        self.base_url = os.getenv("COINBASE_BASE", "https://api.cdp.coinbase.com" if advanced else "https://api.coinbase.com")
        self.advanced = advanced

        # Initialize attributes used by helpers
        self.failed_endpoints = set()
        self.detected_permissions = {}
        self.token = None  # reserved for JWT if you add it

        logger.info(f"CoinbaseClient initialized. advanced={self.advanced} base={self.base_url} debug={self.debug}")

        # Probe endpoints
        try:
            self.detect_api_permissions()
        except Exception as e:
            logger.warning(f"detect_api_permissions raised an exception (non-fatal): {e}")

    def request(self, method="GET", path="/", headers=None, json_body=None, timeout=10):
        url = self.base_url.rstrip("/") + path
        hdrs = headers or {}
        hdrs.setdefault("Accept", "application/json")
        try:
            r = requests.request(method, url, headers=hdrs, json=json_body, timeout=timeout)
            data = r.json() if r.content else None
            if self.debug:
                logger.info(f"[DEBUG] {method} {url} -> {r.status_code} body={data}")
            return r.status_code, data
        except Exception as e:
            logger.warning(f"HTTP request failed for {url}: {e}")
            return None, None

    def detect_api_permissions(self):
        candidate_paths = ["/v3/accounts", "/v2/accounts", "/v2/brokerage/accounts", "/accounts"]
        for p in candidate_paths:
            status, _ = self.request("GET", p)
            if status is None or status >= 400:
                self.failed_endpoints.add(p)
                continue
            if status == 200:
                self.detected_permissions["accounts_path"] = p
                return
        logger.info("No accounts endpoint succeeded during probe.")

    # Example fetch method
    def fetch_advanced_accounts(self):
        for path in ["/v3/accounts", "/v2/accounts", "/v2/brokerage/accounts", "/accounts"]:
            if path in self.failed_endpoints:
                continue
            status, body = self.request("GET", path)
            if status == 200 and body:
                accounts = body.get("data") if isinstance(body, dict) else body
                return accounts
        return []
