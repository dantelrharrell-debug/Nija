# app/nija_client.py
# Python 3.9+ recommended. Requires: pyjwt, cryptography, requests, loguru

import os
import time
import datetime
import jwt
import requests
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

class CoinbaseClient:
    def __init__(self, api_key: str, org_id: str, pem: str):
        self.api_key = api_key
        self.org_id = org_id
        self.pem = pem
        self.jwt_token = None

    def generate_jwt(self):
        """Generate JWT for Coinbase Advanced API"""
        private_key = serialization.load_pem_private_key(
            self.pem.encode(),
            password=None,
            backend=default_backend()
        )
        now = int(time.time())
        payload = {
            "iat": now,
            "exp": now + 300,
            "sub": self.org_id
        }
        self.jwt_token = jwt.encode(payload, private_key, algorithm="ES256")
        return self.jwt_token

    def request(self, method: str, url: str, **kwargs):
        """Perform authenticated Coinbase request"""
        if not self.jwt_token:
            self.generate_jwt()
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self.jwt_token}"
        headers["CB-VERSION"] = "2023-10-15"  # example version
        response = requests.request(method, url, headers=headers, **kwargs)
        if response.status_code == 401:
            logger.error("Unauthorized! Check your API key, org_id, or PEM.")
        return response
