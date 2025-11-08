import os
import time
import hmac
import hashlib
import base64
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

        if not all([self.api_key, self.api_secret, self.passphrase]):
            raise ValueError("Coinbase API credentials are not set in the environment.")

    def _sign(self, method, path):
        ts = str(int(time.time()))
        prehash = ts + method.upper() + path
        sig = base64.b64encode(
            hmac.new(self.api_secret.encode(), prehash.encode(), hashlib.sha256).digest()
        ).decode()
        return ts, sig

    def get_accounts(self):
        path = "/v2/accounts"
        ts, sig = self._sign("GET", path)
        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": sig,
            "CB-ACCESS-TIMESTAMP": ts,
            "CB-ACCESS-PASSPHRASE": self.passphrase,
            "CB-VERSION": "2025-11-02",
            "Content-Type": "application/json"
        }
        r = requests.get(self.base_url + path, headers=headers, timeout=15)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, r.text
