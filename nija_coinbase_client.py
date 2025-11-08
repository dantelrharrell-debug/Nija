import os
import requests
import time
import hmac
import hashlib
import base64
from loguru import logger

class CoinbaseClient:
    def __init__(self, advanced=False):
        """
        Initializes Coinbase client.

        Parameters:
        advanced (bool): If True, uses Coinbase Advanced API, passphrase not required.
        """
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")
        self.advanced = advanced

        if not self.api_key or not self.api_secret:
            raise ValueError("Coinbase API key and secret must be set")

        if not advanced and not self.passphrase:
            raise ValueError("Coinbase API passphrase not set for standard API")

        logger.success(f"CoinbaseClient initialized (Advanced={self.advanced})")

    def _get_headers(self, method, path, body=""):
        """
        Generate authentication headers for Coinbase API.
        """
        timestamp = str(int(time.time()))
        message = timestamp + method.upper() + path + body
        secret_bytes = base64.b64decode(self.api_secret)
        signature = hmac.new(secret_bytes, message.encode(), hashlib.sha256).digest()
        signature_b64 = base64.b64encode(signature).decode()

        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": signature_b64,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json"
        }

        if not self.advanced:
            headers["CB-ACCESS-PASSPHRASE"] = self.passphrase

        return headers

    def get_accounts(self):
        """
        Fetch all accounts from Coinbase (works with standard or Advanced API)
        """
        path = "/v2/accounts"
        url = self.base_url + path
        headers = self._get_headers("GET", path)

        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            raise ValueError(f"Error fetching accounts: {response.status_code} {response.text}")

        return response.json()
