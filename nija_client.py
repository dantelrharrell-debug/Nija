# nija_client.py
import os
import time
import hmac
import hashlib
import base64
import requests
from loguru import logger

class CoinbaseAdvancedClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.pro.coinbase.com")

        if not all([self.api_key, self.api_secret, self.passphrase]):
            logger.error("Coinbase Advanced API credentials missing!")
            raise ValueError("Missing Coinbase Advanced API credentials")
        
        logger.info("Coinbase Advanced client initialized")

    def _get_headers(self, method, request_path, body=""):
        timestamp = str(time.time())
        message = timestamp + method.upper() + request_path + body
        hmac_key = base64.b64decode(self.api_secret)
        signature = hmac.new(hmac_key, message.encode(), hashlib.sha256)
        signature_b64 = base64.b64encode(signature.digest()).decode()

        return {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": signature_b64,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "CB-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json"
        }

    def get_accounts(self):
        request_path = "/accounts"
        headers = self._get_headers("GET", request_path)
        response = requests.get(self.base_url + request_path, headers=headers)
        response.raise_for_status()
        return response.json()

    def get_account(self, account_id):
        request_path = f"/accounts/{account_id}"
        headers = self._get_headers("GET", request_path)
        response = requests.get(self.base_url + request_path, headers=headers)
        response.raise_for_status()
        return response.json()

    def place_order(self, side, product_id, size, price=None, order_type="market"):
        request_path = "/orders"
        body = {
            "side": side,             # 'buy' or 'sell'
            "product_id": product_id, # e.g., 'BTC-USD'
            "type": order_type,       # 'market' or 'limit'
            "size": str(size)
        }

        if order_type == "limit":
            if price is None:
                raise ValueError("Price must be set for limit orders")
            body["price"] = str(price)

        import json
        body_json = json.dumps(body)
        headers = self._get_headers("POST", request_path, body_json)
        response = requests.post(self.base_url + request_path, headers=headers, data=body_json)
        response.raise_for_status()
        return response.json()
