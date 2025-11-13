# app/nija_client.py
import os
import requests
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import jwt
import time

class CoinbaseClient:
    def __init__(self):
        self.api_key_id = os.environ.get("COINBASE_API_KEY_ID")
        self.pem_content = os.environ.get("COINBASE_PEM")
        self.org_id = os.environ.get("COINBASE_ORG_ID")
        self.base_url = "https://api.coinbase.com/api/v3/brokerage"

        if not self.api_key_id or not self.pem_content or not self.org_id:
            raise RuntimeError("Missing Coinbase credentials or org ID!")

        # Load PEM for JWT
        self.private_key = serialization.load_pem_private_key(
            self.pem_content.encode(), password=None, backend=default_backend()
        )
        logger.info("CoinbaseClient initialized with org ID {}", self.org_id)

    # --- JWT generation ---
    def _generate_jwt(self, method="GET", path="/"):
        iat = int(time.time())
        payload = {
            "iat": iat,
            "exp": iat + 300,  # token valid for 5 min
            "sub": self.api_key_id,
            "request_path": path,
            "method": method,
        }
        token = jwt.encode(payload, self.private_key, algorithm="ES256")
        return token

    # --- Accounts ---
    def get_accounts(self):
        path = f"/organizations/{self.org_id}/accounts"
        url = self.base_url + path
        headers = {
            "Authorization": f"Bearer {self._generate_jwt('GET', path)}",
            "CB-VERSION": "2025-11-12"
        }
        resp = requests.get(url, headers=headers)
        if resp.status_code != 200:
            logger.error("HTTP %s: %s", resp.status_code, resp.text)
            resp.raise_for_status()
        return resp.json()

    # --- Historic market data ---
    def get_historic_prices(self, symbol, granularity="60"):
        path = f"/market_data/{symbol}/candles?granularity={granularity}"
        url = self.base_url + path
        headers = {
            "Authorization": f"Bearer {self._generate_jwt('GET', path)}",
            "CB-VERSION": "2025-11-12"
        }
        resp = requests.get(url, headers=headers)
        if resp.status_code != 200:
            logger.error("Historic prices HTTP %s: %s", resp.status_code, resp.text)
            return []
        data = resp.json().get("data", [])
        return data

    # --- Place orders ---
    def place_order(self, account_id, symbol, side, size):
        path = "/orders"
        url = self.base_url + path
        payload = {
            "account_id": account_id,
            "symbol": symbol,
            "side": side.lower(),
            "type": "market",
            "size": str(size)
        }
        headers = {
            "Authorization": f"Bearer {self._generate_jwt('POST', path)}",
            "CB-VERSION": "2025-11-12",
            "Content-Type": "application/json"
        }
        resp = requests.post(url, headers=headers, json=payload)
        if resp.status_code != 201:
            logger.error("Order failed HTTP %s: %s", resp.status_code, resp.text)
            return None
        logger.info("Order placed: %s %s %s", side.upper(), size, symbol)
        return resp.json()
