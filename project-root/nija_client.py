#!/usr/bin/env python3
# nija_client.py
import os
import json
from loguru import logger
from coinbase_advanced_py.advanced import CoinbaseAdvanced

class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.api_passphrase = os.getenv("COINBASE_API_PASSPHRASE")  # Optional for CDP
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.cdp.coinbase.com")

        if not self.api_key or not self.api_secret:
            logger.error("❌ Missing required Coinbase API credentials.")
            raise ValueError("Missing Coinbase API_KEY or API_SECRET in environment")

        # Fix PEM line breaks if present
        self.api_secret = self.api_secret.replace("\\n", "\n")

        # Initialize Advanced client
        self.client = CoinbaseAdvanced(
            api_key=self.api_key,
            api_secret=self.api_secret,
            api_passphrase=self.api_passphrase,
            base_url=self.base_url,
        )

        logger.info(f"✅ CoinbaseClient initialized (base_url={self.base_url})")

    def get_accounts(self):
        try:
            logger.info("ℹ️ Fetching accounts from Coinbase Advanced API...")
            accounts = self.client.get_accounts()
            logger.info(f"✅ Accounts fetched: {len(accounts)}")
            return accounts
        except Exception as e:
            logger.error(f"❌ Error fetching accounts: {e}")
            raise

if __name__ == "__main__":
    client = CoinbaseClient()
    try:
        accounts = client.get_accounts()
        print(json.dumps(accounts, indent=2))
    except Exception as e:
        print("Error fetching accounts:", e)
