# nija_client.py
import os
import requests
import time
import hmac
import hashlib
import json

class CoinbaseClient:
    def __init__(self):
        # Load keys from environment
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

        # Validate required keys
        if not all([self.api_key, self.api_secret]):
            raise ValueError("❌ COINBASE_API_KEY and COINBASE_API_SECRET must be set in environment variables")

        # Passphrase is ignored (Coinbase Advanced API)
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE", None)
        if self.passphrase:
            print("ℹ️ COINBASE_API_PASSPHRASE detected but ignored for Coinbase Advanced API")

    def _get_headers(self, method, path, body=""):
        """
        Generate request headers for Coinbase API.
        Passphrase is not used for Coinbase Advanced.
        """
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
            "Content-Type": "application/json"
        }

    def get_accounts(self):
        url = f"{self.base_url}/v2/accounts"
        headers = self._get_headers("GET", "/v2/accounts")
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
