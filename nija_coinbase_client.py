import os
import time
import hmac
import hashlib
import base64
import requests
from loguru import logger
import jwt

class CoinbaseClient:
    def __init__(self):
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.base_url = os.getenv("COINBASE_API_BASE", "https://api.cdp.coinbase.com")
        if not all([self.api_key, self.api_secret]):
            raise ValueError("Coinbase API key/secret missing!")

        logger.info("CoinbaseClient initialized for Advanced API.")

    def _headers(self):
        # JWT auth for Advanced API
        payload = {
            "iat": int(time.time()),
            "exp": int(time.time()) + 30,
            "sub": self.api_key
        }
        token = jwt.encode(payload, self.api_secret, algorithm="HS256")
        return {"Authorization": f"Bearer {token}"}

    def get_funded_accounts(self, min_balance=0.0):
        url = f"{self.base_url}/platform/v2/evm/accounts"
        resp = requests.get(url, headers=self._headers())
        if resp.status_code != 200:
            return {"ok": False, "status": resp.status_code, "error": resp.text}

        accounts = resp.json().get("data", [])
        funded = [a for a in accounts if float(a.get("balance", 0)) >= min_balance]
        return {"ok": True, "funded_accounts": funded}

    def place_order(self, account_id, side, product, size):
        url = f"{self.base_url}/platform/v2/evm/orders"
        data = {
            "account_id": account_id,
            "side": side,
            "product": product,
            "size": str(size)
        }
        resp = requests.post(url, json=data, headers=self._headers())
        if resp.status_code == 201:
            return {"ok": True, "order": resp.json()}
        else:
            return {"ok": False, "error": resp.text}
