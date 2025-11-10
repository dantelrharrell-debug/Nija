# nija_client.py
import os
import requests
from loguru import logger

class CoinbaseClient:
    """
    Minimal Coinbase API client for Nija bot.
    Uses REST API key/secret from environment variables.
    """

    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.base_url = os.getenv("COINBASE_BASE_URL", "https://api.coinbase.com")

        if not self.api_key or not self.api_secret:
            logger.error("Coinbase API key or secret missing.")
            raise ValueError("Missing Coinbase credentials")

        logger.info("CoinbaseClient initialized")

    def get_account(self):
        """Example method to test connectivity"""
        url = f"{self.base_url}/v2/accounts"
        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": self.api_secret,
        }
        try:
            r = requests.get(url, headers=headers)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error(f"Coinbase connection error: {e}")
            raise
