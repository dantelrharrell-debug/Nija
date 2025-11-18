import logging
from coinbase_advanced_py import Client  # Correct import

class CoinbaseClient:
    def __init__(self, api_key: str, api_secret_path: str, api_passphrase: str, api_sub: str):
        try:
            self.client = Client(
                key=api_key,
                pem_file_path=api_secret_path,
                passphrase=api_passphrase,
                sub=api_sub
            )
            logging.info("✅ CoinbaseClient initialized successfully.")
        except Exception as e:
            logging.error(f"❌ Failed to initialize CoinbaseClient: {e}")
            raise e

    def create_order(self, product_id: str, side: str, type: str, size: str):
        try:
            order = self.client.create_order(
                product_id=product_id,
                side=side,
                type=type,
                size=size
            )
            logging.info(f"✅ Order created: {order}")
            return order
        except Exception as e:
            logging.error(f"❌ Coinbase create_order failed for {product_id} {side} {size}: {e}")
            raise e
