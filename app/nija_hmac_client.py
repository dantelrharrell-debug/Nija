# nija_hmac_client.py
import requests
from loguru import logger
import time
import hmac
import hashlib

class CoinbaseClient:
    def __init__(self, api_key=None, api_secret=None, base="https://api.cdp.coinbase.com"):
        self.api_key = api_key or "<YOUR_API_KEY>"
        self.api_secret = api_secret or "<YOUR_API_SECRET>"
        self.base = base
        self.headers = {
            "CB-ACCESS-KEY": self.api_key,
            "Content-Type": "application/json"
        }

    def _sign(self, method, path, body=""):
        """Generate HMAC signature for Coinbase Advanced API."""
        timestamp = str(int(time.time()))
        message = timestamp + method.upper() + path + body
        signature = hmac.new(
            self.api_secret.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()
        return timestamp, signature

    def request(self, method="GET", path="", body=""):
        url = self.base + path
        timestamp, signature = self._sign(method, path, body)

        headers = self.headers.copy()
        headers.update({
            "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": timestamp
        })

        try:
            response = requests.request(method, url, headers=headers, data=body)
        except Exception as e:
            logger.exception(f"❌ HTTP request failed: {e}")
            return None, None

        try:
            data = response.json()
        except Exception:
            logger.warning(f"⚠️ JSON decode failed. Status: {response.status_code}, Body: {response.text}")
            data = None

        return response.status_code, data
