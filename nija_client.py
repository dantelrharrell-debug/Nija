import os
import json
import requests
from loguru import logger

logger.remove()
logger.add(lambda msg: print(msg, end=""), level="INFO")

class CoinbaseClient:
    def __init__(self, advanced=None, debug=False):
        self.debug = debug

        # API credentials
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.api_passphrase = os.getenv("COINBASE_API_PASSPHRASE", "")  # optional

        # Validate keys early
        missing_keys = []
        if not self.api_key:
            missing_keys.append("COINBASE_API_KEY")
        if not self.api_secret:
            missing_keys.append("COINBASE_API_SECRET")
        if advanced and not self.api_passphrase:
            missing_keys.append("COINBASE_API_PASSPHRASE (required for advanced API)")

        if missing_keys:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_keys)}")

        # Determine API type
        if advanced is None:
            if os.getenv("COINBASE_API_KEY_ADVANCED"):
                self.base = "https://api.cdp.coinbase.com"
                self.advanced = True
            else:
                self.base = "https://api.coinbase.com"
                self.advanced = False
        else:
            self.advanced = advanced
            self.base = "https://api.cdp.coinbase.com" if advanced else "https://api.coinbase.com"

        logger.info(f"CoinbaseClient initialized. advanced={self.advanced} base={self.base} debug={self.debug}")

        # Auto-check which API works
        self.detect_api_permissions()

        # Keep track of inaccessible endpoints to skip them
        self.failed_endpoints = set()

    def request(self, method, path):
        url = self.base + path
        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": self.api_secret,
            "CB-ACCESS-PASSPHRASE": self.api_passphrase,
            "Content-Type": "application/json"
        }
        try:
            r = requests.request(method, url, headers=headers, timeout=10)
            try:
                body = r.json()
            except Exception:
                body = r.text
            if self.debug:
                logger.info(f"[DEBUG] {method} {url} | Status: {r.status_code} | Body: {body}")
            return r.status_code, body
        except Exception as e:
            logger.error(f"[DEBUG] Request failed for {url}: {e}")
            return None, None

    def detect_api_permissions(self):
        """
        Checks which API is accessible and updates self.advanced/base.
        """
        # Try Advanced API
        adv_base = "https://api.cdp.coinbase.com"
        self.base = adv_base
        status, _ = self.request("GET", "/v2/accounts")
        if status == 200:
            self.advanced = True
            logger.info("Advanced API is accessible with current keys.")
            return
        else:
            self.failed_endpoints.add("/v2/accounts")

        # Fallback to Spot API
        spot_base = "https://api.coinbase.com"
        self.base = spot_base
        status, _ = self.request("GET", "/v2/accounts")
        if status == 200:
            self.advanced = False
            logger.info("Spot API is accessible with current keys.")
        else:
            self.failed_endpoints.add("/v2/accounts")
            logger.warning("Neither Advanced nor Spot API is accessible. Check API key permissions.")

    def fetch_advanced_accounts(self):
        paths = ["/v3/accounts", "/v2/accounts"]
        for path in paths:
            if path in self.failed_endpoints:
                logger.debug(f"Skipping previously failed endpoint {path}")
                continue
            status, body = self.request("GET", path)
            if status == 200 and body:
                accounts = body.get("data", []) if isinstance(body, dict) else []
                logger.info(f"Fetched {len(accounts)} accounts from {path}")
                return accounts
            elif status == 404:
                logger.warning(f"{path} returned 404; trying next endpoint.")
                self.failed_endpoints.add(path)
        logger.error("Failed to fetch accounts. No endpoint succeeded.")
        return []

    def fetch_spot_accounts(self):
        paths = ["/v2/accounts"]
        for path in paths:
            if path in self.failed_endpoints:
                logger.debug(f"Skipping previously failed endpoint {path}")
                continue
            status, body = self.request("GET", path)
            if status == 200 and body:
                accounts = body.get("data", []) if isinstance(body, dict) else []
                logger.info(f"Fetched {len(accounts)} spot accounts from {path}")
                return accounts
            else:
                logger.warning(f"{path} returned {status}; cannot fetch spot accounts.")
                self.failed_endpoints.add(path)
        logger.error("Failed to fetch spot accounts.")
        return []
