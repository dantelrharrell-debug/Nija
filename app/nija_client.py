# nija_client.py
import os
import time
import hmac
import hashlib
import requests
import json
import logging

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("nija_client")

class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

        if not all([self.api_key, self.api_secret]):
            raise RuntimeError("❌ Missing Coinbase API credentials")

        if self.passphrase:
            log.info("✅ CoinbaseClient initialized with standard API key + passphrase.")
            self.auth_type = "standard"
        else:
            log.info("⚠️ No passphrase provided. Using Advanced JWT key (no passphrase required).")
            self.auth_type = "jwt"

        log.info("✅ CoinbaseClient initialized successfully (Advanced JWT compatible).")

    def _get_headers(self, method, endpoint, body=""):
        timestamp = str(int(time.time()))
        if self.auth_type == "standard":
            message = timestamp + method.upper() + endpoint + body
            signature = hmac.new(self.api_secret.encode(), message.encode(), hashlib.sha256).hexdigest()
            headers = {
                "CB-ACCESS-KEY": self.api_key,
                "CB-ACCESS-SIGN": signature,
                "CB-ACCESS-TIMESTAMP": timestamp,
                "CB-ACCESS-PASSPHRASE": self.passphrase,
                "Content-Type": "application/json",
            }
        else:  # JWT
            headers = {
                "Authorization": f"Bearer {self.api_secret}",
                "Content-Type": "application/json",
            }
        return headers

    def _send_request(self, endpoint, method="GET", body="", use_jwt=None):
        url = self.base_url + endpoint
        if use_jwt is None:
            use_jwt = self.auth_type == "jwt"

        headers = self._get_headers(method, endpoint, body) if not use_jwt else {
            "Authorization": f"Bearer {self.api_secret}",
            "Content-Type": "application/json",
        }

        response = requests.request(method, url, headers=headers, data=body)
        if response.status_code not in (200, 201):
            log.error(f"❌ Request failed: {response.status_code} {response.text}")
            if response.status_code == 401:
                raise RuntimeError("❌ 401 Unauthorized: Check API key permissions and JWT usage")
            else:
                raise RuntimeError(f"❌ Request failed: {response.status_code} {response.text}")
        return response.json()

    def get_all_accounts(self):
        endpoint = "/v2/accounts"
        return self._send_request(endpoint)

    def get_usd_spot_balance(self):
        accounts_data = self.get_all_accounts()
        for account in accounts_data.get("data", []):
            if account.get("currency") == "USD":
                return float(account.get("balance", {}).get("amount", 0))
        return 0.0

# Helper functions to keep nija_debug.py working exactly as before
client = CoinbaseClient()

def get_all_accounts():
    return client.get_all_accounts()

def get_usd_spot_balance():
    return client.get_usd_spot_balance()
