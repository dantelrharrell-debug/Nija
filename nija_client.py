import os
from loguru import logger

class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")  # optional
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.cdp.coinbase.com")

        if not all([self.api_key, self.api_secret, self.base_url]):
            logger.error("Coinbase API credentials missing.")
            raise ValueError("Missing Coinbase API credentials")

        logger.info("CoinbaseClient initialized successfully")
