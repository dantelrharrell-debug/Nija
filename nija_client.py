import json
import time
import jwt
import requests
from pathlib import Path

class CoinbaseClient:
    """
    Minimal Coinbase Advanced API client for live trading.
    """
    def __init__(self, api_key, api_secret_path, api_passphrase="", api_sub=""):
        self.api_key = api_key
        self.api_secret_path = Path(api_secret_path)
        self.api_passphrase = api_passphrase
        self.api_sub = api_sub
        self.base_url = "https://api.coinbase.com"
        self.load_pem()
    
    def load_pem(self):
        if not self.api_secret_path.exists():
            raise FileNotFoundError(f"PEM file not found: {self.api_secret_path}")
        self.pem_content = self.api_secret_path.read_text()
    
    def _jwt_headers(self):
        payload = {
            "sub": self.api_sub,
            "iat": int(time.time()),
            "exp": int(time.time()) + 30
        }
        token = jwt.encode(payload, self.pem_content, algorithm="ES256")
        return {
            "Authorization": f"Bearer {token}",
            "CB-VERSION": "2025-01-01",
            "Content-Type": "application/json"
        }

    def create_order(self, product_id, side, type="market", size=None):
        url = f"{self.base_url}/v2/orders"
        headers = self._jwt_headers()
        data = {
            "product_id": product_id,
            "side": side,
            "type": type,
        }
        if size:
            data["size"] = size
        response = requests.post(url, headers=headers, json=data)
        if response.status_code != 200:
            raise Exception(f"Order failed: {response.status_code} | {response.text}")
        return response.json()
    
    def get_accounts(self):
        url = f"{self.base_url}/v2/accounts"
        headers = self._jwt_headers()
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            raise Exception(f"Failed to fetch accounts: {response.status_code} | {response.text}")
        return response.json()
