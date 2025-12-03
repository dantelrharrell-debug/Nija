# nija_coinbase_usd.py
import os
import time
import hmac
import hashlib
import base64
import requests
from decimal import Decimal
from dotenv import load_dotenv
from pathlib import Path

# --- Load environment variables ---
env_path = Path("/app/.env")
load_dotenv(dotenv_path=env_path)

# --- HMAC CoinbaseClient for Retail API ---
class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")  # Optional for Retail
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

        if not all([self.api_key, self.api_secret]):
            raise ValueError("Coinbase API key/secret are not set in the environment.")

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
            "CB-ACCESS-PASSPHRASE": self.passphrase or "",
            "CB-VERSION": "2025-11-08",
            "Content-Type": "application/json"
        }
        r = requests.get(self.base_url + path, headers=headers, timeout=15)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, r.text

    def get_usd_balance(self):
        status, data = self.get_accounts()
        if isinstance(data, dict) and "data" in data:
            usd_account = next((acc for acc in data["data"] if acc.get("currency") == "USD"), None)
            if usd_account:
                return Decimal(usd_account.get("balance", {}).get("amount", "0"))
        return Decimal(0)

# --- Example usage for bot ---
if __name__ == "__main__":
    client = CoinbaseClient()
    usd_balance = client.get_usd_balance()
    print(f"USD Balance (ready for bot use): ${usd_balance}")
