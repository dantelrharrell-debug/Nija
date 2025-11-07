# nija_client.py
import os
import requests
from loguru import logger

class CoinbaseClient:
    """
    Simple Coinbase client for read-only operations.
    Add more methods if needed for trading.
    """
    BASE_URL = "https://api.coinbase.com/v2"

    def __init__(self, api_key=None, api_secret=None, passphrase=None):
        self.api_key = api_key or os.getenv("COINBASE_API_KEY")
        self.api_secret = api_secret or os.getenv("COINBASE_API_SECRET")
        self.passphrase = passphrase or os.getenv("COINBASE_API_PASSPHRASE")

        if not all([self.api_key, self.api_secret]):
            logger.error("Coinbase API credentials are missing")
            raise ValueError("API_KEY and API_SECRET must be set")

    def get_accounts(self):
        """
        Fetch all accounts (read-only)
        """
        url = f"{self.BASE_URL}/accounts"
        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-VERSION": "2023-11-06"
        }
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            return data.get("data", [])
        except Exception as e:
            logger.exception("Failed to fetch accounts")
            raise e

# Initialize a global client instance
client = CoinbaseClient()
