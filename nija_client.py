# nija_client.py

import os
from loguru import logger
import requests
import json
import time
import hmac
import hashlib
import base64

class CoinbaseClient:
    def __init__(self, advanced=True):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")
        self.advanced = advanced

        if not self.api_key or not self.api_secret:
            raise ValueError("Coinbase API key and secret must be set")
        if not advanced and not self.passphrase:
            raise ValueError("Coinbase API passphrase must be set for standard API")

        logger.success(f"CoinbaseClient initialized (Advanced={self.advanced})")

    # Example: simple GET request for accounts
    def get_accounts(self):
        url = f"{self.base_url}/v2/accounts"
        timestamp = str(int(time.time()))
        method = "GET"
        request_path = "/v2/accounts"
        body = ""

        message = timestamp + method + request_path + body
        signature = hmac.new(
            self.api_secret.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()

        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": timestamp,
        }

        # Only add passphrase if standard API
        if not self.advanced and self.passphrase:
            headers["CB-ACCESS-PASSPHRASE"] = self.passphrase

        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
