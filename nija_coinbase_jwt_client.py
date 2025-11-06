import os
import time
import jwt
import requests
from loguru import logger

class CoinbaseJWTClient:
    """
    Minimal JWT-based client for Coinbase Advanced API.
    Uses COINBASE_JWT_KEY_ID and COINBASE_JWT_PRIVATE_KEY from environment.
    """
    def __init__(self):
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.cdp.coinbase.com")
        self.key_id = os.getenv("COINBASE_JWT_KEY_ID")
        self.private_key = os.getenv("COINBASE_JWT_PRIVATE_KEY")

        if not all([self.key_id, self.private_key]):
            raise ValueError("Missing COINBASE_JWT_KEY_ID or COINBASE_JWT_PRIVATE_KEY in env")

        logger.info("[NIJA-JWT] Coinbase JWT client initialized.")

    def _get_headers(self):
        payload = {
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
            "sub": self.key_id
        }
        token = jwt.encode(payload, self.private_key, algorithm="ES256")
        return {"Authorization": f"Bearer {token}"}

    def list_accounts(self):
        url = f"{self.base_url}/v2/accounts"
        headers = self._get_headers()
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", [])

    def get_account_balance(self, account_id):
        url = f"{self.base_url}/v2/accounts/{account_id}/balances"
        headers = self._get_headers()
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()
