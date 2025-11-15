import os
import time
import json
import requests
import jwt  # pip install PyJWT
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

class CoinbaseClient:
    def __init__(self, api_key=None, org_id=None, pem=None, kid=None):
        self.api_key = api_key or os.getenv("COINBASE_API_KEY")
        self.org_id = org_id or os.getenv("COINBASE_ORG_ID")
        self._kid = str(kid or os.getenv("COINBASE_KID"))
        self._private_key_pem = pem or os.getenv("COINBASE_PEM_CONTENT")

        if not all([self.api_key, self.org_id, self._kid, self._private_key_pem]):
            raise ValueError("Missing Coinbase credentials or PEM")

        self._private_key = self._load_private_key()
        logger.info(f"CoinbaseClient initialized with kid: {self._kid}")

    def _load_private_key(self):
        return serialization.load_pem_private_key(
            self._private_key_pem.encode(), password=None, backend=default_backend()
        )

    def _build_jwt(self):
        now = int(time.time())
        payload = {
            "sub": f"organizations/{self.org_id}/apiKeys/{self.api_key}",
            "iat": now,
            "exp": now + 300
        }
        headers = {"kid": self._kid, "alg": "ES256", "typ": "JWT"}
        token = jwt.encode(payload, self._private_key, algorithm="ES256", headers=headers)
        return token

    def request_auto(self, method, endpoint, data=None):
        url = f"https://api.coinbase.com{endpoint}"
        headers = {
            "Authorization": f"Bearer {self._build_jwt()}",
            "CB-VERSION": "2025-01-01",
            "Content-Type": "application/json"
        }
        try:
            response = requests.request(method.upper(), url, headers=headers, json=data)
            if response.status_code == 200:
                return response.status_code, response.json()
            content = {}
            try: content = response.json()
            except: content = {"error": response.text}
            return response.status_code, content
        except Exception as e:
            logger.error(f"Request failed: {e}")
            return None, {}
