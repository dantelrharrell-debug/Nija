# app/nija_client.py

import os
import time
import jwt
import requests
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

class CoinbaseClient:
    def __init__(self):
        # --- Load environment variables ---
        self.org_id = os.environ.get("COINBASE_ORG_ID")
        self.api_key = os.environ.get("COINBASE_API_KEY")
        self.pem_raw = os.environ.get("COINBASE_PEM_CONTENT")

        # Optional debug
        logger.info(f"COINBASE_ORG_ID length: {len(self.org_id) if self.org_id else 'None'}")
        logger.info(f"COINBASE_API_KEY length: {len(self.api_key) if self.api_key else 'None'}")
        logger.info(f"COINBASE_PEM_CONTENT length: {len(self.pem_raw) if self.pem_raw else 'None'}")

        if not all([self.org_id, self.api_key, self.pem_raw]):
            raise ValueError("Missing Coinbase credentials in environment variables!")

        # --- Fix PEM formatting ---
        self.pem_fixed = self.pem_raw.replace("\\n", "\n").strip()

        # Debug PEM head/tail
        logger.info(f"PEM head: {self.pem_fixed.splitlines()[0]}")
        logger.info(f"PEM tail: {self.pem_fixed.splitlines()[-1]}")

        # --- Load private key ---
        self.private_key = serialization.load_pem_private_key(
            self.pem_fixed.encode(),
            password=None,
            backend=default_backend()
        )

    def generate_jwt(self):
        """Generates JWT for Coinbase Advanced API"""
        iat = int(time.time())
        payload = {
            "sub": self.org_id,
            "iat": iat,
            "exp": iat + 300  # Token valid for 5 minutes
        }

        token = jwt.encode(
            payload,
            self.private_key,
            algorithm="ES256",
            headers={"kid": self.api_key}
        )

        # Debug JWT preview (first 50 chars)
        logger.info(f"Generated JWT preview: {str(token)[:50]}")
        return token

    def request(self, method, url, **kwargs):
        """Example: use generated JWT for an API request"""
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self.generate_jwt()}"
        headers["Content-Type"] = "application/json"
        return requests.request(method, url, headers=headers, **kwargs)
