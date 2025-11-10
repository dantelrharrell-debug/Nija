import os
import json
import logging
import requests
from loguru import logger

logger = logging.getLogger("nija_client")
logger.setLevel(logging.INFO)

class CoinbaseClient:
    def __init__(self, advanced=False, base=None):
        self.advanced = advanced
        self.base = base or os.getenv("COINBASE_BASE", "https://api.cdp.coinbase.com")
        logger.info(f"CoinbaseClient initialized. advanced={self.advanced} base={self.base}")
        # Normally init auth headers, PEM, etc.
        self.api_key = os.getenv("COINBASE_ISS")

    def request(self, method, path):
        url = self.base + path
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            resp = requests.request(method, url, headers=headers)
            if resp.status_code == 200:
                return 200, resp.json()
            else:
                return resp.status_code, resp.text
        except Exception as e:
            logger.error(f"Request error: {e}")
            return 500, None

    def fetch_advanced_accounts(self):
        paths = ["/v3/accounts", "/v2/accounts"]
        for path in paths:
            status, body = self.request("GET", path)
            if status == 200 and body:
                accounts = body.get("data", []) if isinstance(body, dict) else []
                logger.info(f"Fetched {len(accounts)} accounts from {path}")
                return accounts
            elif status == 404:
                logger.warning(f"{path} returned 404; trying next endpoint.")
        logger.error("Failed to fetch accounts. No endpoint succeeded.")
        return []

    def get_accounts(self):
        # Spot API fallback
        status, body = self.request("GET", "/accounts")
        if status == 200 and body:
            accounts = body.get("data", []) if isinstance(body, dict) else []
            logger.info(f"Fetched {len(accounts)} spot accounts")
            return accounts
        logger.error("Failed to fetch spot accounts.")
        return []
