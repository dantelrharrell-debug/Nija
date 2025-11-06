# nija_client.py
import os
import time
import hmac
import hashlib
import requests
import json

class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.cdp.coinbase.com")  # Advanced API endpoint

        if not all([self.api_key, self.api_secret]):
            raise ValueError("❌ COINBASE_API_KEY or COINBASE_API_SECRET not set in environment variables")

        print("✅ CoinbaseClient initialized (Advanced API)")

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
            "Content-Type": "application/json"
        }

    def get_accounts(self):
        """Fetch accounts from Coinbase Advanced API"""
        url = f"{self.base_url}/platform/v2/accounts"
        headers = self._get_headers("GET", "/platform/v2/accounts")

        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            print("✅ Accounts fetched successfully")
            return data
        except requests.exceptions.HTTPError as e:
            if response.status_code in (401, 403):
                print("❌ Unauthorized: check API key/secret or permissions.")
                return None
            raise e
        except Exception as e:
            print(f"❌ Error fetching accounts: {e}")
            return None
