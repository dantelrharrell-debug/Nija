import json
import requests
import logging

class CoinbaseClient:
    def __init__(self, api_key, api_secret_path, api_passphrase, api_sub):
        self.api_key = api_key
        self.api_secret_path = api_secret_path
        self.api_passphrase = api_passphrase
        self.api_sub = api_sub
        # You can load PEM here if needed
        logging.info("✅ CoinbaseClient initialized (stub)")

    def create_order(self, product_id, side, type, size):
        # Stub: replace with real REST API call later
        logging.info(f"🚀 Stub order: {side} {size} {product_id}")
        return {"id": "stub-order-id", "product_id": product_id, "side": side, "size": size}
