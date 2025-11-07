# nija_client.py
import os
import requests
import jwt
import time
from loguru import logger

class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")
        self.pem_path = os.getenv("COINBASE_PEM_PATH")

        if not all([self.api_key, self.api_secret, self.passphrase, self.pem_path]):
            logger.warning("Some Coinbase credentials are missing. Check Render env variables.")

        logger.info("Coinbase client initialized")

    def get_accounts(self):
        """Retrieve accounts from Coinbase Advanced API (JWT auth)."""
        timestamp = str(int(time.time()))
        method = "GET"
        request_path = "/v2/accounts"
        message = timestamp + method + request_path
        signature = jwt.encode(
            {"iat": int(time.time())},
            open(self.pem_path, "r").read(),
            algorithm="RS256"
        )

        headers = {
            "CB-ACCESS-KEY": self.api_key,
            "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "CB-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json"
        }

        url = self.base_url + request_path
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
