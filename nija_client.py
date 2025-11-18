import json
import logging
from coinbase_advanced_py.rest_client import RestClient  # Official REST client

class CoinbaseClient:
    def __init__(self, api_key, api_secret_path, api_passphrase="", api_sub=""):
        self.api_key = api_key
        self.api_secret_path = api_secret_path
        self.api_passphrase = api_passphrase
        self.api_sub = api_sub
        self.client = None
        self.load_client()

    def load_client(self):
        try:
            with open(self.api_secret_path, "r") as f:
                pem_content = f.read()
            self.client = RestClient(
                api_key=self.api_key,
                api_secret=pem_content,
                api_passphrase=self.api_passphrase,
                subaccount=self.api_sub
            )
            logging.info("✅ Coinbase client initialized successfully.")
        except FileNotFoundError:
            logging.error(f"❌ PEM file not found: {self.api_secret_path}")
            raise
        except Exception as e:
            logging.error(f"❌ Failed to initialize Coinbase client: {e}")
            raise

    def create_order(self, product_id, side, type="market", size="0"):
        if not self.client:
            raise Exception("Coinbase client not initialized.")
        try:
            order = self.client.create_order(
                product_id=product_id,
                side=side,
                type=type,
                size=size
            )
            return order
        except Exception as e:
            logging.error(f"❌ Coinbase order failed: {e}")
            raise
