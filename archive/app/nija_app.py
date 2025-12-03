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

        if not all([self.api_key_id, self.pem_content, self.org_id]):
            raise RuntimeError("Missing Coinbase credentials or org ID!")

        # Load PEM safely
        try:
            self.private_key = serialization.load_pem_private_key(
                self.pem_content.strip().encode(), password=None, backend=default_backend()
            )
        except Exception as e:
            raise RuntimeError("Failed to load Coinbase private key") from e

        logger.info("CoinbaseClient initialized with org ID {}", self.org_id)

    def _generate_jwt(self, method="GET", path="/"):
        # Validate method and path
        ALLOWED_METHODS = {"GET", "POST", "PUT", "DELETE"}
        if method not in ALLOWED_METHODS:
            raise ValueError(f"Invalid HTTP method: {method}")
        if not path.startswith("/organizations/"):
            raise ValueError(f"Invalid API path: {path}")

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

    def get_accounts(self):
        path = f"/organizations/{self.org_id}/accounts"
        url = self.base_url + path
        headers = {
            "Authorization": f"Bearer {self._generate_jwt('GET', path)}",
            "CB-VERSION": "2025-11-12"
        }
        resp = requests.get(url, headers=headers)
        if resp.status_code != 200:
            logger.error("HTTP %s error when fetching accounts", resp.status_code)
            resp.raise_for_status()
        return resp.json().get("data", [])
