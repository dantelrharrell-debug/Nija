import os
import requests
from loguru import logger

class CoinbaseClient:
    """
    Nija CoinbaseClient for Advanced + Classic API.
    Initializes with environment variables:
    - COINBASE_API_KEY
    - COINBASE_API_SECRET
    """

    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.base_url = "https://api.coinbase.com/v2"
        self.classic_url = "https://api.coinbase.com/v2/accounts"  # placeholder

        if not self.api_key or not self.api_secret:
            raise ValueError("Missing Coinbase API credentials")

        logger.info("CoinbaseClient initialized successfully")

    def get_accounts(self):
        """
        Example Advanced API call.
        Returns dict with 'data' key containing accounts.
        """
        try:
            url = f"{self.base_url}/accounts"
            headers = {
                "CB-ACCESS-KEY": self.api_key,
                "CB-ACCESS-SIGN": self.api_secret,  # placeholder, add proper JWT signing if needed
            }
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                return resp.json()
            logger.warning(f"[Advanced API] Status {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.error(f"[Advanced API] Exception: {e}")
        return None

    def get_classic_accounts(self):
        """
        Fallback Classic API call.
        Returns dict with 'data' key containing accounts.
        """
        try:
            headers = {"Authorization": f"Bearer {self.api_secret}"}
            resp = requests.get(self.classic_url, headers=headers, timeout=10)
            if resp.status_code == 200:
                return resp.json()
            logger.warning(f"[Classic API] Status {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.error(f"[Classic API] Exception: {e}")
        return None
