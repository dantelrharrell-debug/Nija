# --- nija_client.py ---
import os
import tempfile
import requests
import json
import logging

class CoinbaseClient:
    def __init__(self, api_key, api_secret_path=None, api_passphrase="", api_sub=""):
        self.api_key = api_key
        self.api_passphrase = api_passphrase
        self.api_sub = api_sub
        self.api_secret_path = api_secret_path
        self.pem_content = os.getenv("COINBASE_PEM_CONTENT")  # load from env if set
        self.load_pem()
        logging.info("✅ CoinbaseClient initialized successfully")

    def load_pem(self):
        """
        Loads the PEM key either from environment or file.
        """
        if self.pem_content:
            tmp = tempfile.NamedTemporaryFile(delete=False)
            tmp.write(self.pem_content.encode())
            tmp.flush()
            self.api_secret_path = tmp.name
            logging.info(f"PEM loaded from environment variable into {self.api_secret_path}")
        elif self.api_secret_path and os.path.exists(self.api_secret_path):
            logging.info(f"PEM loaded from file {self.api_secret_path}")
        else:
            raise FileNotFoundError(f"PEM file not found: {self.api_secret_path}")

    def create_order(self, product_id, side, type="market", size="0.001"):
        """
        Simplified placeholder. Replace with actual Coinbase Advanced API call.
        """
        # TODO: Replace this with actual API integration
        logging.info(f"🚀 Placing order: {side} {size} {product_id} (placeholder)")
        # Example return object
        return {"id": "order1234", "product_id": product_id, "side": side, "size": size}
