# nija_client.py
import os
import time
import hmac
import hashlib
import base64
import requests
from loguru import logger

class NijaClient:
    """
    Simple Coinbase client using JWT/REST API
    """

    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.api_passphrase = os.getenv("COINBASE_API_PASSPHRASE")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.exchange.coinbase.com")

        if not all([self.api_key, self.api_secret, self.api_passphrase]):
            raise ValueError("Missing Coinbase API credentials in environment variables.")

    def _get_headers(self, method, path, body=""):
        timestamp = str(int(time.time()))
        message = timestamp + method + path + body
        hmac_key = base64.b64decode(self.api_secret)
        signature = hmac.new(hmac_key, message.encode(), hashlib.sha256).digest()
        signature_b64 = base64.b64encode(signature).decode()

        return {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": signature_b64,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "CB-ACCESS-PASSPHRASE": self.api_passphrase,
            "Content-Type": "application/json"
        }

    def get_accounts(self):
        path = "/accounts"
        url = self.base_url + path
        headers = self._get_headers("GET", path)
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            logger.error(f"Failed to fetch accounts: {response.status_code} {response.text}")
            return None
        return response.json()

    def place_order(self, order_data: dict):
        path = "/orders"
        url = self.base_url + path
        body = json.dumps(order_data)
        headers = self._get_headers("POST", path, body)
        response = requests.post(url, headers=headers, data=body)
        if response.status_code not in [200, 201]:
            logger.error(f"Order failed: {response.status_code} {response.text}")
            return None
        return response.json()
