import os
import requests
import time
import jwt
import hmac
import hashlib
import base64

# ===============================
# COINBASE CLIENT
# ===============================
class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.api_passphrase = os.getenv("COINBASE_API_PASSPHRASE")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

        if not all([self.api_key, self.api_secret, self.api_passphrase]):
            raise ValueError("Missing Coinbase API credentials in environment variables")

    def _get_auth_headers(self, method="GET", path="/", body=""):
        timestamp = str(int(time.time()))
        message = timestamp + method + path + body
        hmac_key = base64.b64decode(self.api_secret)
        signature = hmac.new(hmac_key, message.encode(), hashlib.sha256).hexdigest()

        return {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "CB-ACCESS-PASSPHRASE": self.api_passphrase,
            "Content-Type": "application/json"
        }

    def get_accounts(self):
        path = "/accounts"
        url = self.base_url + path
        headers = self._get_auth_headers("GET", path)
        r = requests.get(url, headers=headers)
        r.raise_for_status()
        return r.json()


# ===============================
# Alias for Railway / old imports
# ===============================
CoinbaseClientWrapper = CoinbaseClient  # <- fixes import error on Railway
