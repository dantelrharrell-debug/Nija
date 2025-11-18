# --- nija_client.py ---
import json
from coinbase_advanced.client import Client  # Official package
import logging

class CoinbaseClient:
    def __init__(self, api_key: str, api_secret_path: str, api_passphrase: str, api_sub: str):
        self.api_key = api_key
        self.api_secret_path = api_secret_path
        self.api_passphrase = api_passphrase
        self.api_sub = api_sub
        self.client = None
        self.load_client()

    def load_client(self):
        """Initialize Coinbase Advanced client safely."""
        try:
            # Load PEM file content
            with open(self.api_secret_path, "r") as f:
                pem_content = f.read()

            # Initialize official Coinbase Advanced client
            self.client = Client(
                api_key=self.api_key,
                api_secret=pem_content,
                api_passphrase=self.api_passphrase,
                api_sub=self.api_sub
            )
            logging.info("✅ Coinbase Advanced client initialized successfully")

        except FileNotFoundError:
            logging.error(f"❌ PEM file not found: {self.api_secret_path}")
            raise
        except Exception as e:
            logging.error(f"❌ Failed to initialize Coinbase client: {e}")
            raise

    def create_order(self, product_id: str, side: str, type: str, size: str):
        """Place a market order."""
        try:
            order = self.client.order.create(
                product_id=product_id,
                side=side,
                type=type,
                size=size
            )
            logging.info(f"✅ Order placed: {side} {size} {product_id}")
            return order
        except Exception as e:
            logging.error(f"❌ Failed to create order {side} {size} {product_id}: {e}")
            raise

    def get_accounts(self):
        """Fetch account balances."""
        try:
            accounts = self.client.account.list()
            return accounts
        except Exception as e:
            logging.error(f"❌ Failed to fetch accounts: {e}")
            raise
