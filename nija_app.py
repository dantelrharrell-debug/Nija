# nija_client.py
import os
import time
import hmac
import hashlib
import base64
import requests

class CoinbaseClient:
    """
    Simple Coinbase client for live trading.
    Make sure the following environment variables are set:
    COINBASE_API_KEY, COINBASE_API_SECRET, COINBASE_API_PASSPHRASE
    """
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.exchange.coinbase.com")

        if not all([self.api_key, self.api_secret, self.passphrase]):
            raise ValueError("Missing Coinbase API credentials")

    def _sign(self, method, path, body=""):
        timestamp = str(int(time.time()))
        message = timestamp + method.upper() + path + body
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
        headers = self._sign("GET", path)
        url = self.base_url + path
        r = requests.get(url, headers=headers)
        r.raise_for_status()
        return r.json()

    def place_order(self, side, product_id, size):
        """
        Place a live order on Coinbase.
        side: "buy" or "sell"
        product_id: e.g., "BTC-USD"
        size: amount in base currency, as string
        """
        path = "/orders"
        body = {
            "side": side,
            "product_id": product_id,
            "size": size,
            "type": "market"
        }
        import json
        body_json = json.dumps(body)
        headers = self._sign("POST", path, body_json)
        url = self.base_url + path
        r = requests.post(url, headers=headers, data=body_json)
        r.raise_for_status()
        return r.json()
