# nija_client.py
import os
import requests
import time
import hmac
import hashlib
import base64
import jwt

class CoinbaseClient:
    def __init__(self):
        # Load keys from environment
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.api_passphrase = os.getenv("COINBASE_API_PASSPHRASE")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

        if not all([self.api_key, self.api_secret, self.api_passphrase]):
            raise ValueError("API keys or passphrase are not set in environment variables")

    def _get_headers(self, method, path, body=""):
        timestamp = str(int(time.time()))
        message = f"{timestamp}{method}{path}{body}"
        signature = hmac.new(
            self.api_secret.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()

        return {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "CB-ACCESS-PASSPHRASE": self.api_passphrase,
            "Content-Type": "application/json"
        }

    def get_accounts(self):
        url = f"{self.base_url}/v2/accounts"
        headers = self._get_headers("GET", "/v2/accounts")
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
