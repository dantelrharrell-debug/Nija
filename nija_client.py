import os
import time
import hmac
import hashlib
import base64
import requests
import json

class CoinbaseClient:
    def __init__(self):
        # Load API credentials from environment
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        # Passphrase is optional for Advanced API
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE", None)
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.cdp.coinbase.com")

        if not all([self.api_key, self.api_secret]):
            raise ValueError("COINBASE_API_KEY and COINBASE_API_SECRET must be set")

    def _get_headers(self, method, path, body=""):
        timestamp = str(int(time.time()))
        message = timestamp + method.upper() + path + body
        signature = hmac.new(
            self.api_secret.encode(), message.encode(), hashlib.sha256
        ).hexdigest()

        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json",
        }
        # Only include passphrase if it exists (for Pro keys)
        if self.passphrase:
            headers["CB-ACCESS-PASSPHRASE"] = self.passphrase
        return headers

    def get_accounts(self):
        path = "/platform/v2/accounts"
        url = self.base_url + path
        headers = self._get_headers("GET", path)
        resp = requests.get(url, headers=headers)
        if resp.status_code >= 400:
            resp.raise_for_status()
        return resp.json().get("data", [])

    def submit_order(self, account_id, side, size, price=None, order_type="market"):
        path = f"/platform/v2/accounts/{account_id}/orders"
        body = {"side": side, "size": size, "type": order_type}
        if price:
            body["price"] = price
        body_json = json.dumps(body)
        headers = self._get_headers("POST", path, body_json)
        resp = requests.post(self.base_url + path, headers=headers, data=body_json)
        if resp.status_code >= 400:
            resp.raise_for_status()
        return resp.json()
