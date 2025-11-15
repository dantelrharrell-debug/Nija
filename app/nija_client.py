# app/nija_client.py
# Python 3.9+ recommended. Requires: pyjwt, cryptography, requests, loguru

import jwt
import time
import requests
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

class CoinbaseClient:
    def __init__(self, api_key: str, org_id: str, pem: str):
        self.api_key = api_key
        self.org_id = org_id
        # Fix PEM line breaks
        self.pem = pem.replace("\\n", "\n").encode()
        self.private_key = serialization.load_pem_private_key(
            self.pem,
            password=None,
            backend=default_backend()
        )
        logger.info("CoinbaseClient initialized.")

    def generate_jwt(self):
        now = int(time.time())
        payload = {
            "iat": now,
            "exp": now + 300,  # 5 minutes expiration
            "jti": str(now),
            "org_id": self.org_id
        }
        token = jwt.encode(
            payload,
            self.private_key,
            algorithm="ES256",
            headers={"kid": self.api_key}
        )
        return token

    def request(self, method, url, **kwargs):
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self.generate_jwt()}"
        response = requests.request(method, url, headers=headers, **kwargs)
        return response
