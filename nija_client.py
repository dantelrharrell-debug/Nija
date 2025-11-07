# nija_client.py
import os
import time
import hmac
import hashlib
import base64
import requests
from loguru import logger

class CoinbaseClient:
    """
    Coinbase Advanced API client (LIVE trading ready)
    """
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.cdp.coinbase.com")

        if not all([self.api_key, self.api_secret, self.passphrase]):
            logger.error("Coinbase API keys or passphrase not set!")
            raise ValueError("Missing Coinbase API credentials")

        logger.info("CoinbaseClient initialized successfully")

    def _get_headers(self, method, path, body=""):
        """
        Create the headers required for Coinbase Advanced API authentication
        """
        timestamp = str(int(time.time()))
        message = f"{timestamp}{method}{path}{body}"
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "CB-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json"
        }
        return headers

    def get_accounts(self):
        """
        Get live accounts info
        """
        path = "/platform/v2/accounts"
        url = self.base_url + path
        headers = self._get_headers("GET", path)
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()

    def place_order(self, product_id, side, size, price=None, order_type="market"):
        """
        Place a buy/sell order
        """
        path = "/platform/v2/orders"
        url = self.base_url + path
        order = {
            "product_id": product_id,
            "side": side,
            "type": order_type,
            "size": str(size)
        }
        if order_type == "limit" and price:
            order["price"] = str(price)

        import json
        body = json.dumps(order)
        headers = self._get_headers("POST", path, body)
        response = requests.post(url, headers=headers, data=body)
        response.raise_for_status()
        return response.json()
