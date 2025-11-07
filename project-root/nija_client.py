# nija_client.py
import os
import time
import hmac
import hashlib
import requests
from loguru import logger

class NijaCoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_PASSPHRASE")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

        if not all([self.api_key, self.api_secret, self.passphrase]):
            logger.error("Missing Coinbase API credentials!")
            raise SystemExit(1)

    def _get_headers(self, method, path, body=""):
        timestamp = str(int(time.time()))
        message = timestamp + method + path + body
        signature = hmac.new(
            self.api_secret.encode(), message.encode(), hashlib.sha256
        ).hexdigest()
        return {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "CB-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
        }

    def get_accounts(self):
        path = "/accounts"
        url = self.base_url + path
        headers = self._get_headers("GET", path)
        r = requests.get(url, headers=headers)
        return r.json()
