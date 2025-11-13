# app/nija_client.py
import os
import time
import requests
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import jwt

class CoinbaseClient:
    def __init__(self):
        self.api_key_id = os.environ.get("COINBASE_API_KEY_ID")
        self.pem_content = os.environ.get("COINBASE_PEM")
        self.org_id = os.environ.get("COINBASE_ORG_ID")
        self.base_url = "https://api.coinbase.com/api/v3/brokerage"

        if not self.api_key_id or not self.pem_content or not self.org_id:
            raise RuntimeError("Missing Coinbase credentials or org ID!")

        # Load PEM for JWT signing
        self.private_key = serialization.load_pem_private_key(
            self.pem_content.encode(), password=None, backend=default_backend()
        )
        logger.info("CoinbaseClient initialized with org ID {}", self.org_id)

    # --- Internal JWT generator ---
    def _generate_jwt(self, method="GET", path="/"):
        iat = int(time.time())
        payload = {
            "iat": iat,
            "exp": iat + 300,  # 5 min validity
            "sub": self.api_key_id,
            "request_path": path,
            "method": method,
        }
        token = jwt.encode(payload, self.private_key, algorithm="ES256")
        return token

    # --- Helper request method ---
    def _request(self, method, path, data=None):
        url = self.base_url + path
        headers = {
            "Authorization": f"Bearer {self._generate_jwt(method, path)}",
            "CB-VERSION": "2025-11-12",
            "Content-Type": "application/json"
        }
        try:
            if method.upper() == "GET":
                resp = requests.get(url, headers=headers)
            elif method.upper() == "POST":
                resp = requests.post(url, headers=headers, json=data)
            else:
                raise ValueError("Unsupported HTTP method")

            if resp.status_code >= 400:
                logger.error("HTTP %s: %s", resp.status_code, resp.text)
                resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error("Request failed: %s", e)
            raise

    # --- Accounts ---
    def get_accounts(self):
        path = f"/organizations/{self.org_id}/accounts"
        return self._request("GET", path)

    # --- Candles / Market Data ---
    def get_candles(self, symbol, granularity=60):
        """
        granularity in seconds: 60=1m, 300=5m, 900=15m, etc.
        """
        path = f"/market_data/{symbol}/candles?granularity={granularity}"
        return self._request("GET", path).get("data", [])

    # --- Place orders ---
    def place_order(self, account_id, symbol, side, size):
        """
        side = 'buy' or 'sell'
        size = float amount in base currency
        """
        path = "/orders"
        data = {
            "account_id": account_id,
            "symbol": symbol,
            "side": side.lower(),
            "size": str(size)
        }
        return self._request("POST", path, data)
