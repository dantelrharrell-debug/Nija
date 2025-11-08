# nija_hmac_client.py
import os
import time
import hmac
import hashlib
import requests

class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.api_base = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

        if not self.api_key or not self.api_secret:
            raise Exception("COINBASE_API_KEY or COINBASE_API_SECRET not set in environment.")

    def _get_signature(self, method, path, body=""):
        timestamp = str(int(time.time()))
        message = timestamp + method + path + body
        signature = hmac.new(
            self.api_secret.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()
        return timestamp, signature

    def get_accounts(self):
        method = "GET"
        path = "/v2/accounts"
        timestamp, signature = self._get_signature(method, path)
        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "CB-VERSION": "2025-11-08"
        }
        response = requests.get(self.api_base + path, headers=headers)
        return response.status_code, response.json()
