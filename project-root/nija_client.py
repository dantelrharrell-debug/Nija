import os
import requests
import hmac
import hashlib
import time
import json
from loguru import logger

class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

        if not all([self.api_key, self.api_secret, self.passphrase]):
            logger.error("Coinbase API credentials are missing!")
            raise ValueError("Missing Coinbase API credentials")
        else:
            logger.info("CoinbaseClient initialized successfully ✅")

    def _headers(self, method: str, path: str, body: str = ""):
        timestamp = str(int(time.time()))
        message = f"{timestamp}{method.upper()}{path}{body}"
        hmac_key = hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256
        )
        signature = hmac_key.hexdigest()

        return {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "CB-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json"
        }

    def get_accounts(self):
        path = "/v2/accounts"
        url = self.base_url + path
        headers = self._headers("GET", path)
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            logger.error(f"Error fetching accounts: {response.status_code} {response.text}")
            return []
        data = response.json()
        return data.get("data", [])
