# nija_hmac_client.py
import os
import time
import hmac
import hashlib
import requests
from loguru import logger

class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.base_url = "https://api.cdp.coinbase.com"

    def request(self, method="GET", path="/v2/accounts", body=None):
        body = body or {}
        timestamp = str(int(time.time()))
        message = timestamp + method + path + (str(body) if body else "")
        signature = hmac.new(
            self.api_secret.encode(), message.encode(), hashlib.sha256
        ).hexdigest()

        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json",
        }

        url = self.base_url + path
        response = requests.request(method, url, headers=headers, json=body)
        return response.status_code, response.json()
