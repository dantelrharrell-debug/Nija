# nija_client.py
import os
import time
import requests
from loguru import logger
import base64
import hmac
import hashlib
import json

class CoinbaseClient:
    def __init__(self, api_key=None, api_secret=None, passphrase=None, base=None, advanced_mode=True):
        self.api_key = api_key or os.getenv("COINBASE_API_KEY")
        self.api_secret = api_secret or os.getenv("COINBASE_API_SECRET")
        self.passphrase = passphrase or os.getenv("COINBASE_API_PASSPHRASE")
        self.advanced_mode = advanced_mode

        # Automatically select the correct base URL
        if base:
            self.base = base
        elif self.advanced_mode:
            self.base = "https://api.cdp.coinbase.com"
        else:
            self.base = "https://api.pro.coinbase.com"

        logger.info(f"CoinbaseClient initialized — Advanced mode: {self.advanced_mode}")

    def _get_headers(self, method="GET", request_path="", body=""):
        """Generate authentication headers for Coinbase Pro API"""
        timestamp = str(int(time.time()))
        message = timestamp + method + request_path + body
        hmac_key = base64.b64decode(self.api_secret)
        signature = hmac.new(hmac_key, message.encode(), hashlib.sha256).digest()
        signature_b64 = base64.b64encode(signature).decode()

        return {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": signature_b64,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "CB-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
        }

    def fetch_accounts(self):
        """Fetch account balances, automatically choosing endpoint based on mode"""
        try:
            if self.advanced_mode:
                url = f"{self.base}/accounts"  # CDP endpoint
                headers = {
                    "CB-ACCESS-KEY": self.api_key,
                    "CB-ACCESS-SIGN": "FAKE_SIGNATURE",
                    "CB-ACCESS-TIMESTAMP": str(int(time.time())),
                    "CB-ACCESS-PASSPHRASE": self.passphrase,
                }
                resp = requests.get(url, headers=headers)
            else:
                url = "/accounts"
                full_url = self.base + url
                headers = self._get_headers("GET", url)
                resp = requests.get(full_url, headers=headers)

            resp.raise_for_status()
            data = resp.json()

            # Normalize for both APIs
            if "data" in data:  # CDP
                return data["data"]
            elif isinstance(data, list):  # Pro API
                return data
            else:
                return []

        except Exception as e:
            logger.error(f"Error fetching accounts: {e}")
            return []

    def get_balances(self):
        """Return a dict of balances by currency"""
        accounts = self.fetch_accounts()
        balances = {}
        for acct in accounts:
            currency = acct.get("currency") or acct.get("asset")
            balance = float(acct.get("balance", 0) or acct.get("available", 0))
            balances[currency] = balance
        return balances
