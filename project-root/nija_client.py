# nija_client.py
import os
import requests
from loguru import logger

class CoinbaseClient:
    BASE_URL = "https://api.coinbase.com/v2"

    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")  # optional, if using auth
        if not all([self.api_key, self.api_secret]):
            logger.error("Coinbase API credentials missing")
            raise ValueError("API_KEY and API_SECRET must be set")
        logger.info("Coinbase client initialized")

    def get_accounts(self):
        """
        Example read-only API call to Coinbase.
        """
        url = f"{self.BASE_URL}/accounts"
        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-VERSION": "2023-11-06"
        }
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            return data.get("data", [])
        except Exception as e:
            logger.exception("Failed to fetch accounts")
            return []

# Create a **global client instance** so nija_app.py can import it
client = CoinbaseClient()
