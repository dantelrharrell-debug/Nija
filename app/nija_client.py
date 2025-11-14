# /app/nija_client.py
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
        self.api_key = os.environ.get("COINBASE_API_KEY", "")
        self.org_id = os.environ.get("COINBASE_ORG_ID", "")
        self.base_url = "https://api.coinbase.com"

        # Load PEM from base64
        pem_b64 = os.environ.get("COINBASE_PEM_B64", "")
        if not pem_b64:
            raise ValueError("COINBASE_PEM_B64 not set or empty")
        try:
            pem_bytes = base64.b64decode(pem_b64)
            self.private_key = serialization.load_pem_private_key(
                pem_bytes,
                password=None,
                backend=default_backend()
            )
            logger.info("PEM loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load PEM: {e}")
            raise e

    def generate_jwt(self):
        now = int(time.time())
        payload = {
            "iat": now,
            "exp": now + 300,  # 5 minutes
            "sub": self.api_key,
            "org_id": self.org_id
        }
        try:
            token = jwt.encode(
                payload,
                self.private_key,
                algorithm="ES256"
            )
            return token
        except Exception as e:
            logger.error(f"JWT generation failed: {e}")
            return None

    def make_request(self, method, endpoint, **kwargs):
        jwt_token = self.generate_jwt()
        if not jwt_token:
            logger.error("No JWT, skipping request.")
            return None

        headers = kwargs.pop("headers", {})
        headers.update({
            "Authorization": f"Bearer {jwt_token}",
            "CB-VERSION": "2025-11-14"
        })

        url = f"{self.base_url}{endpoint}"
        try:
            response = requests.request(method, url, headers=headers, **kwargs)
            if response.status_code >= 400:
                logger.error(f"Coinbase API error: {response.status_code} {response.text}")
            return response
        except Exception as e:
            logger.error(f"Request failed: {e}")
            return None

# Quick test (optional)
if __name__ == "__main__":
    client = CoinbaseClient()
    resp = client.make_request("GET", "/v2/accounts")
    if resp:
        logger.info(resp.json())
