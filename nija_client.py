import os
import time
import hmac
import hashlib
import base64
import requests
from coinbase_advanced_py import CoinbaseClient  # Ensure coinbase-advanced-py is installed

class NijaCoinbaseClient:
    """
    NIJA Coinbase Client for live trading.
    Uses REST API keys from environment variables and handles signing requests.
    """

    def __init__(self):
        # Load credentials from environment variables
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.passphrase = os.getenv("COINBASE_API_PASSPHRASE")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.cdp.coinbase.com")

        if not all([self.api_key, self.api_secret, self.passphrase]):
            raise ValueError("API_KEY, API_SECRET, and API_PASSPHRASE must be set in environment variables.")

        # Initialize the official Coinbase Advanced client
        self.client = CoinbaseClient(api_key=self.api_key, api_secret=self.api_secret, passphrase=self.passphrase)

        print("⚡ NIJA bot is LIVE! Real trades will execute.")

    def get_accounts(self):
        """Fetch all accounts with balances."""
        try:
            accounts = self.client.get_accounts()
            return accounts
        except Exception as e:
            print(f"[ERROR] Failed to fetch accounts: {e}")
            return None

    def place_order(self, product_id, side, size, price=None, order_type="market"):
        """
        Place a buy/sell order.
        order_type: "market" or "limit"
        """
        try:
            order_data = {
                "product_id": product_id,
                "side": side,
                "size": size,
                "type": order_type,
            }
            if order_type == "limit" and price is not None:
                order_data["price"] = price

            response = self.client.create_order(**order_data)
            print(f"[ORDER] {side.upper()} {size} {product_id} at {price if price else 'MARKET'} executed.")
            return response
        except Exception as e:
            print(f"[ERROR] Failed to place order: {e}")
            return None

    def get_product_ticker(self, product_id):
        """Fetch the latest price and market info for a product."""
        try:
            ticker = self.client.get_product_ticker(product_id)
            return ticker
        except Exception as e:
            print(f"[ERROR] Failed to fetch ticker for {product_id}: {e}")
            return None

    def wait_and_retry(self, func, *args, retries=3, delay=1, **kwargs):
        """Retry a function a few times if it fails."""
        for attempt in range(retries):
            result = func(*args, **kwargs)
            if result:
                return result
            print(f"[WARN] Attempt {attempt+1} failed, retrying in {delay}s...")
            time.sleep(delay)
        print("[ERROR] Maximum retries reached.")
        return None

# Example usage (uncomment to test)
# if __name__ == "__main__":
#     client = NijaCoinbaseClient()
#     accounts = client.get_accounts()
#     print(accounts)
#     ticker = client.get_product_ticker("BTC-USD")
#     print(ticker)
#     client.place_order(product_id="BTC-USD", side="buy", size="0.001")
