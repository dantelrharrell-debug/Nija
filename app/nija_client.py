# nija_client.py
import os
import json
import time
import logging
import base64
import requests
import jwt  # PyJWT
from pathlib import Path

class CoinbaseClient:
    def __init__(self, api_key, api_secret_path, api_passphrase="", api_sub=""):
        self.api_key = api_key
        self.api_secret_path = api_secret_path
        self.api_passphrase = api_passphrase
        self.api_sub = api_sub
        self.base_url = "https://api.coinbase.com"
        self.headers = {}
        self.load_pem()
        self.generate_jwt()
        logging.info("✅ CoinbaseClient initialized")

    def load_pem(self):
        """Load EC private key from file"""
        if not Path(self.api_secret_path).exists():
            raise FileNotFoundError(f"PEM file not found: {self.api_secret_path}")
        with open(self.api_secret_path, "r") as f:
            self.pem = f.read()
        logging.info("✅ PEM loaded successfully")

    def generate_jwt(self):
        """Generate JWT token for authentication"""
        now = int(time.time())
        payload = {
            "iat": now,
            "exp": now + 60,
            "sub": self.api_sub
        }
        try:
            self.jwt_token = jwt.encode(payload, self.pem, algorithm="ES256")
            self.headers = {
                "Authorization": f"Bearer {self.jwt_token}",
                "CB-VERSION": "2025-01-01",
                "Content-Type": "application/json"
            }
            logging.info("✅ JWT generated")
        except Exception as e:
            logging.error(f"❌ Failed to generate JWT: {e}")
            raise

    def create_order(self, product_id, side, type="market", size="0.0", account_id=None):
        """Place a market order on Coinbase Advanced"""
        url = f"{self.base_url}/v3/brokerage/orders"
        order_data = {
            "client_order_id": f"order_{int(time.time()*1000)}",
            "product_id": product_id,
            "side": side,
            "type": type,
            "size": str(size)
        }
        if account_id:
            order_data["account_id"] = account_id

        try:
            response = requests.post(url, headers=self.headers, data=json.dumps(order_data))
            if response.status_code not in [200, 201]:
                logging.error(f"❌ Order failed: {response.status_code} | {response.text}")
                return None
            result = response.json()
            logging.info(f"✅ Order executed: {result}")
            return result
        except Exception as e:
            logging.error(f"❌ Exception while creating order: {e}")
            return None

    # Optional: add more Coinbase API methods here
    # def get_account(self, account_id):
    #     ...
