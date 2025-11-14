# app/nija_client.py
import os
import time
import jwt
import requests
import base64
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

logger.remove()
logger.add(lambda m: print(m, end=""))

class CoinbaseClient:
    def __init__(self):
        self.org_id = os.environ.get("COINBASE_ORG_ID")
        self.api_key = os.environ.get("COINBASE_API_KEY")
        self.pem_b64 = os.environ.get("COINBASE_PEM_B64", "")

        if not self.pem_b64:
            raise ValueError("COINBASE_PEM_B64 environment variable is missing")

        # Decode the base64 PEM into bytes
        pem_bytes = base64.b64decode(self.pem_b64)

        # Load private key from bytes
        self.private_key = serialization.load_pem_private_key(
            pem_bytes,
            password=None,
            backend=default_backend()
        )

    def generate_jwt(self):
        now = int(time.time())
        payload = {
            "iat": now,
            "exp": now + 300,  # 5 minutes
            "sub": self.org_id,
        }
        token = jwt.encode(payload, self.private_key, algorithm="ES256")
        return token

    def make_request(self, endpoint):
        jwt_token = self.generate_jwt()
        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "CB-ACCESS-KEY": self.api_key,
            "Content-Type": "application/json"
        }
        url = f"https://api.coinbase.com{endpoint}"
        response = requests.get(url, headers=headers)
        return response.json()
