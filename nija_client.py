# nija_client.py
import os
import requests
from loguru import logger

class CoinbaseClient:
    def __init__(self, api_key=None, api_secret=None, api_passphrase=None):
        self.api_key = api_key or os.getenv("COINBASE_API_KEY")
        self.api_secret = api_secret or os.getenv("COINBASE_API_SECRET")
        self.api_passphrase = api_passphrase or os.getenv("COINBASE_API_PASSPHRASE")
        self.base = "https://api.coinbase.com/v2"
        logger.info(f"CoinbaseClient initialized. base={self.base}")

    def _request(self, endpoint, method="GET", params=None):
        url = f"{self.base}{endpoint}"
        headers = {
            "CB-VERSION": "2025-11-11",  # use a recent version
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        try:
            response = requests.request(method, url, headers=headers, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.warning(f"HTTP request failed for {url}: {e}")
            return None

    def get_accounts(self):
        """
        Fetch your Coinbase accounts (wallets) using v2 API.
        """
        data = self._request("/accounts")
        if not data or "data" not in data:
            logger.warning("/accounts returned no data or failed")
            return []
        return data["data"]

# Quick test
if __name__ == "__main__":
    client = CoinbaseClient()
    accounts = client.get_accounts()
    if accounts:
        logger.info(f"Found {len(accounts)} accounts.")
    else:
        logger.warning("No accounts found.")
