# nija_hmac_client.py
import os, time, hmac, hashlib, base64, requests, json
from dotenv import load_dotenv

load_dotenv()

class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")  # retail only
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")
        if not all([self.api_key, self.api_secret]):
            raise ValueError("COINBASE_API_KEY and COINBASE_API_SECRET must be set")

    def _sign(self, method, path):
        ts = str(int(time.time()))
        prehash = ts + method.upper() + path
        sig = base64.b64encode(hmac.new(self.api_secret.encode(), prehash.encode(), hashlib.sha256).digest()).decode()
        return ts, sig

    def get_accounts(self):
        path = "/v2/accounts"
        ts, sig = self._sign("GET", path)
        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": sig,
            "CB-ACCESS-TIMESTAMP": ts,
            "CB-ACCESS-PASSPHRASE": self.passphrase or "",
            "CB-VERSION": "2025-11-02",
            "Content-Type": "application/json"
        }
        r = requests.get(self.base_url + path, headers=headers, timeout=15)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, r.text
