import os
import time
import hmac
import hashlib
import base64
import requests
from loguru import logger

class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

        if not all([self.api_key, self.api_secret, self.passphrase]):
            logger.error("Coinbase API credentials missing.")
            raise ValueError("Missing Coinbase API credentials")

    def _get_headers(self, method, path, body=""):
        timestamp = str(int(time.time()))
        message = f"{timestamp}{method.upper()}{path}{body}"
        hmac_key = base64.b64decode(self.api_secret)
        signature = hmac.new(hmac_key, message.encode("utf-8"), hashlib.sha256).digest()
        signature_b64 = base64.b64encode(signature).decode()
        return {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": signature_b64,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "CB-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json"
        }

    def get_accounts(self):
        path = "/accounts"
        url = f"{self.base_url}{path}"
        headers = self._get_headers("GET", path)
        r = requests.get(url, headers=headers)
        r.raise_for_status()
        return r.json()

    def place_order(self, product_id, side, price, size, order_type="limit"):
        path = "/orders"
        body = {"product_id": product_id, "side": side, "price": price, "size": size, "type": order_type}
        body_json = json.dumps(body)
        headers = self._get_headers("POST", path, body_json)
        url = f"{self.base_url}{path}"
        r = requests.post(url, headers=headers, data=body_json)
        r.raise_for_status()
        return r.json()
