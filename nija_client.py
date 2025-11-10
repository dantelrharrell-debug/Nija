import os
import json
import requests
from loguru import logger

logger.remove()
logger.add(lambda msg: print(msg, end=""), level="INFO")

class CoinbaseClient:
    def __init__(self, advanced=None):
        # Auto-detect advanced vs spot
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.api_passphrase = os.getenv("COINBASE_API_PASSPHRASE", "")  # optional for advanced

        if advanced is None:
            # If advanced keys exist, use Advanced API
            if os.getenv("COINBASE_API_KEY_ADVANCED"):
                self.base = "https://api.cdp.coinbase.com"
                self.advanced = True
            else:
                self.base = "https://api.coinbase.com"
                self.advanced = False
        else:
            self.advanced = advanced
            self.base = "https://api.cdp.coinbase.com" if advanced else "https://api.coinbase.com"

        logger.info(f"CoinbaseClient initialized. advanced={self.advanced} base={self.base}")

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
                body = None
            return r.status_code, body
        except Exception as e:
            logger.error(f"Request failed for {url}: {e}")
            return None, None

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

    def fetch_spot_accounts(self):
        paths = ["/v2/accounts"]
        for path in paths:
            status, body = self.request("GET", path)
            if status == 200 and body:
                accounts = body.get("data", []) if isinstance(body, dict) else []
                logger.info(f"Fetched {len(accounts)} spot accounts from {path}")
                return accounts
            else:
                logger.warning(f"{path} returned {status}; cannot fetch spot accounts.")
        logger.error("Failed to fetch spot accounts.")
        return []
