# nija_client.py
import json
import logging
from coinbase_advanced_py import RestClient  # Make sure coinbase_advanced_py is installed

class CoinbaseClient:
    def __init__(self, api_key, api_secret_path, api_passphrase, api_sub):
        self.api_key = api_key
        self.api_secret_path = api_secret_path
        self.api_passphrase = api_passphrase
        self.api_sub = api_sub

        # Initialize Coinbase REST client
        try:
            with open(api_secret_path, "r") as f:
                pem_content = f.read()
            self.client = RestClient(
                api_key=self.api_key,
                pem_content=pem_content,
                api_passphrase=self.api_passphrase,
                api_sub=self.api_sub
            )
            logging.info("✅ Coinbase client initialized.")
        except Exception as e:
            logging.error(f"❌ Failed to initialize Coinbase client: {e}")
            raise e

    def create_order(self, product_id, side, type="market", size="0"):
        """
        Executes a market order.
        """
        try:
            order = self.client.create_order(
                product_id=product_id,
                side=side,
                type=type,
                size=str(size)
            )
            return order
        except Exception as e:
            logging.error(f"❌ Failed to place order for {product_id}: {e}")
            return None

    def get_account_balance(self, currency="USD"):
        """
        Returns available balance for a currency (USD, BTC, ETH, etc.)
        """
        try:
            account = self.client.get_account(currency)
            return float(account["available"]) if "available" in account else 0
        except Exception as e:
            logging.error(f"❌ Failed to fetch balance for {currency}: {e}")
            return 0

    def get_ticker_price(self, product_id):
        """
        Fetches current price of the trading pair.
        """
        try:
            ticker = self.client.get_ticker(product_id)
            return float(ticker["price"]) if "price" in ticker else 0
        except Exception as e:
            logging.error(f"❌ Failed to fetch ticker for {product_id}: {e}")
            return 0
