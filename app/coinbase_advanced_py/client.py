import os
import logging
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

class Client:
    """
    Simple Coinbase Advanced Client for REST calls.
    """
    BASE_URL = "https://api.coinbase.com"

    def __init__(self, api_key=None, api_secret=None, api_sub=None):
        self.api_key = api_key or os.environ.get("COINBASE_API_KEY")
        self.api_secret = api_secret or os.environ.get("COINBASE_API_SECRET")
        self.api_sub = api_sub or os.environ.get("COINBASE_API_SUB")
        if not all([self.api_key, self.api_secret]):
            logging.warning("Coinbase API credentials not fully set.")
        else:
            logging.info("Coinbase client initialized with credentials.")

    def get_accounts(self):
        """
        Example: fetch accounts to test connection.
        """
        url = f"{self.BASE_URL}/v2/accounts"
        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": "FAKE_SIGN_FOR_TEST",  # placeholder for demo
            "CB-ACCESS-TIMESTAMP": "0",
            "CB-ACCESS-PASSPHRASE": self.api_sub or "",
        }
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logging.error(f"Failed to fetch Coinbase accounts: {e}")
            return None
