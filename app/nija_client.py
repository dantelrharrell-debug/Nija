# app/nija_client.py

import os
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import requests
from loguru import logger
import time

class CoinbaseClient:
    def __init__(self):
        self.org_id = os.environ.get("COINBASE_ORG_ID")
        self.api_key_id = os.environ.get("COINBASE_API_KEY_ID")
        self.pem_content = os.environ.get("COINBASE_PEM", "")
        self.base_url = "https://api.coinbase.com/api/v3/brokerage"

        # Fix escaped newlines in PEM
        pem_clean = self.pem_content.replace("\\n", "\n")
        self.private_key = serialization.load_pem_private_key(
            pem_clean.encode(), password=None, backend=default_backend()
        )

        logger.info("CoinbaseClient initialized with org ID %s", self.org_id)

    def _generate_jwt(self, method: str, path: str):
        iat = int(time.time())
        payload = {
            "iat": iat,
            "exp": iat + 120,                   # expires in 2 minutes
            "sub": self.api_key_id,             # must be key id
            "request_path": path,
            "method": method,
        }
        headers = {"alg": "ES256", "kid": self.api_key_id}
        token = jwt.encode(payload, self.private_key, algorithm="ES256", headers=headers)

        if os.environ.get("DEBUG_JWT"):
            logger.info("DEBUG_JWT: token_preview=%s", token[:200])
        return token

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
