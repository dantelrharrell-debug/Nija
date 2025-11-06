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
        # Passphrase is optional
        self.api_passphrase = os.getenv("COINBASE_API_PASSPHRASE", None)
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

        # Warn if passphrase is missing (optional)
        if not self.api_key or not self.api_secret:
            raise ValueError("COINBASE_API_KEY or COINBASE_API_SECRET not set in environment variables")
        if self.api_passphrase is None:
            print("⚠️ COINBASE_API_PASSPHRASE not set. Skipping passphrase authentication.")

    def _get_headers(self, method, path, body=""):
        timestamp = str(int(time.time()))
        message = f"{timestamp}{method}{path}{body}"
        signature = hmac.new(
            self.api_secret.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()

        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json"
        }

        # Only include passphrase if set
        if self.api_passphrase:
            headers["CB-ACCESS-PASSPHRASE"] = self.api_passphrase

        return headers

    def get_accounts(self):
        url = f"{self.base_url}/v2/accounts"
        headers = self._get_headers("GET", "/v2/accounts")
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
