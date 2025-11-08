# --- BEGIN get_accounts patch ---
from nija_client import CoinbaseClient as OriginalCoinbaseClient

# Only patch once
if not hasattr(OriginalCoinbaseClient, "get_accounts"):
    def get_accounts(self, *args, **kwargs):
        # Redirect to fetch_accounts
        return self.fetch_accounts(*args, **kwargs)
    
    setattr(OriginalCoinbaseClient, "get_accounts", get_accounts)
# --- END get_accounts patch ---

# nija_client.py
import os
import time
import hmac
import hashlib
import base64
import requests
from loguru import logger

class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.cdp.coinbase.com")

        if not all([self.api_key, self.api_secret]):
            raise ValueError("Missing Coinbase API credentials")

        logger.info("CoinbaseClient initialized successfully.")

    def _sign_request(self, method: str, path: str, body: str = "") -> dict:
        """
        Generates required headers for Coinbase Advanced API request
        """
        timestamp = str(int(time.time()))
        message = timestamp + method.upper() + path + body
        hmac_key = base64.b64decode(self.api_secret)
        signature = hmac.new(hmac_key, message.encode(), hashlib.sha256).digest()
        signature_b64 = base64.b64encode(signature).decode()

        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": signature_b64,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json"
        }
        return headers

    def fetch_accounts(self):
        """
        Fetches a list of accounts from Coinbase Advanced API
        """
        path = "/platform/v2/evm/accounts"  # adjust if needed
        url = self.base_url + path

        headers = self._sign_request("GET", path)
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            # Example: data['accounts'] or adjust according to API response
            accounts = data.get("data", [])
            logger.info(f"Fetched {len(accounts)} accounts.")
            return accounts
        except Exception as e:
            logger.error(f"Error fetching accounts: {e}")
            return []

# Quick test (only run if this file is executed directly)
if __name__ == "__main__":
    client = CoinbaseClient()
    accounts = client.fetch_accounts()
    print(accounts)
